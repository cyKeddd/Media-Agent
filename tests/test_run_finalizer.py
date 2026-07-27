"""Issue 60 — guarantee terminal run state; sweep abandoned runs.

Covers:
  - Repository.sweep_abandoned_runs: finalizes old open rows, leaves young
    rows alone, is idempotent, ignores already-finalized rows.
  - config_loader: run_hang_minutes surfaces with default 90.
  - src.gen_run.sweep_abandoned_runs / src.daily_upload.sweep_abandoned_runs:
    emit a run_abandoned alert per swept row.
  - Both entry points' main() call the sweep only AFTER the run lock is
    acquired — proven by a test where the lock is held.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config_loader import load_config
from src.observability import RunLockHeld
from src.state import Repository, connect, initialize_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_repo(tmp_path) -> Repository:
    db = Path(tmp_path) / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _insert_run(repo: Repository, *, kind: str, minutes_ago: int, finished: bool = False) -> int:
    """Insert a runs row with started_at `minutes_ago` minutes in the past."""
    cur = repo.conn.execute(
        "INSERT INTO runs (kind, started_at) VALUES (?, datetime('now', ?))",
        (kind, f"-{minutes_ago} minutes"),
    )
    run_id = cur.lastrowid
    if finished:
        repo.conn.execute(
            "UPDATE runs SET finished_at=datetime('now'), success=1, summary_json=? "
            "WHERE run_id=?",
            (json.dumps({"ok": True}), run_id),
        )
    return run_id


# ---------------------------------------------------------------------------
# config_loader: run_hang_minutes
# ---------------------------------------------------------------------------


def _minimal_config_dict() -> dict:
    return {
        "clips_per_day": 1,
        "days_per_run": 7,
        "upload_slots": ["09:00"],
        "timezone": "Asia/Singapore",
        "whisper_model": "large-v3",
        "whisper_compute_type": "int8_float16",
        "whisper_device": "cuda",
        "ollama_model": "qwen2.5:3b-instruct",
        "human_review": True,
        "banlist": [],
        "hook_sanity_min_score": 3,
        "profanity_max_score": 5,
        "dedup_lookback_days": 90,
        "phash_min_hamming": 8,
        "output_resolution": [1080, 1920],
        "nvenc_preset": "p5",
        "nvenc_cq": 23,
        "loudness_target_lufs": -14.0,
        "youtube_quota_daily_units": 10000,
        "youtube_quota_ceiling_units": 9000,
        "videos_insert_unit_cost": 1600,
        "ai_gen": {
            "per_clip_cost_cents_max": 300,
            "daily_spend_cents_ceiling": 500,
        },
        "retention": {
            "output_post_upload": 7,
            "rejected_clips": 30,
            "dup_hashes": 90,
            "quota_usage": 90,
            "vacuum_every_days": 30,
        },
        "paths": {
            "state_db": "data/state.db",
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "logs_dir": "logs",
            "oauth_token": "data/oauth_token.json",
            "client_secrets": "data/client_secret.json",
        },
    }


def _write_yaml(tmp_path, payload: dict) -> Path:
    path = Path(tmp_path) / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_run_hang_minutes_defaults_to_90(tmp_path):
    cfg_path = _write_yaml(tmp_path, _minimal_config_dict())
    cfg = load_config(cfg_path)
    assert cfg.run_hang_minutes == 90


def test_run_hang_minutes_configurable(tmp_path):
    payload = _minimal_config_dict()
    payload["run_hang_minutes"] = 45
    cfg_path = _write_yaml(tmp_path, payload)
    cfg = load_config(cfg_path)
    assert cfg.run_hang_minutes == 45


def test_real_config_yaml_has_run_hang_minutes():
    """The committed config.yaml carries the new key explicitly."""
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
    assert cfg.run_hang_minutes == 90


# ---------------------------------------------------------------------------
# Repository.sweep_abandoned_runs
# ---------------------------------------------------------------------------


def test_sweep_finalizes_row_older_than_threshold(tmp_path):
    repo = _new_repo(tmp_path)
    run_id = _insert_run(repo, kind="generation", minutes_ago=100)

    swept = repo.sweep_abandoned_runs(90)

    assert len(swept) == 1
    assert swept[0]["run_id"] == run_id

    row = repo.conn.execute(
        "SELECT finished_at, success, summary_json FROM runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert row["finished_at"] is not None
    assert row["success"] == 0
    parsed = json.loads(row["summary_json"])
    assert parsed["message"] == "abandoned"
    assert "started_at" in parsed


def test_sweep_leaves_row_younger_than_threshold_untouched(tmp_path):
    repo = _new_repo(tmp_path)
    run_id = _insert_run(repo, kind="generation", minutes_ago=5)

    swept = repo.sweep_abandoned_runs(90)

    assert swept == []
    row = repo.conn.execute(
        "SELECT finished_at, success FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    assert row["finished_at"] is None
    assert row["success"] is None


def test_sweep_leaves_already_finalized_row_untouched(tmp_path):
    repo = _new_repo(tmp_path)
    run_id = _insert_run(repo, kind="daily", minutes_ago=200, finished=True)

    swept = repo.sweep_abandoned_runs(90)

    assert swept == []
    row = repo.conn.execute(
        "SELECT success, summary_json FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    assert row["success"] == 1
    assert json.loads(row["summary_json"]) == {"ok": True}


def test_sweep_is_idempotent(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_run(repo, kind="generation", minutes_ago=100)

    first = repo.sweep_abandoned_runs(90)
    second = repo.sweep_abandoned_runs(90)

    assert len(first) == 1
    assert second == []


def test_sweep_handles_multiple_abandoned_rows(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_run(repo, kind="generation", minutes_ago=200)
    _insert_run(repo, kind="daily", minutes_ago=150)
    _insert_run(repo, kind="generation", minutes_ago=10)  # young, untouched

    swept = repo.sweep_abandoned_runs(90)

    assert len(swept) == 2
    count = repo.conn.execute(
        "SELECT COUNT(*) FROM runs WHERE finished_at IS NULL"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# src.gen_run.sweep_abandoned_runs — alert emission
# ---------------------------------------------------------------------------


def test_gen_run_sweep_helper_emits_run_abandoned_alert(tmp_path):
    from src.gen_run import sweep_abandoned_runs

    repo = _new_repo(tmp_path)
    _insert_run(repo, kind="generation", minutes_ago=200)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.run_hang_minutes = 90

    sweep_abandoned_runs(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert "run_abandoned" in alerts


def test_gen_run_sweep_helper_no_alert_when_nothing_abandoned(tmp_path):
    from src.gen_run import sweep_abandoned_runs

    repo = _new_repo(tmp_path)
    _insert_run(repo, kind="generation", minutes_ago=5)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.run_hang_minutes = 90

    sweep_abandoned_runs(repo, cfg, logs_dir)

    alerts_path = logs_dir / "alerts.md"
    if alerts_path.exists():
        assert "run_abandoned" not in alerts_path.read_text(encoding="utf-8")


def test_daily_upload_sweep_helper_emits_run_abandoned_alert(tmp_path):
    from src.daily_upload import sweep_abandoned_runs

    repo = _new_repo(tmp_path)
    _insert_run(repo, kind="daily", minutes_ago=200)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.run_hang_minutes = 90

    sweep_abandoned_runs(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert "run_abandoned" in alerts


# ---------------------------------------------------------------------------
# main() ordering: sweep runs AFTER the run lock is acquired
# ---------------------------------------------------------------------------


def test_gen_run_sweep_not_called_when_lock_held(tmp_path, monkeypatch):
    """Proof that the sweep lives inside the lock block: if the lock is
    held by another process, sweep_abandoned_runs must never run."""
    from src import gen_run

    cfg = MagicMock()
    cfg.abs_path = lambda rel: Path(tmp_path) / rel
    cfg.paths.logs_dir = "logs"
    cfg.paths.state_db = "state.db"
    (Path(tmp_path) / "state.db").write_bytes(b"")

    def _raise_lock_held(_lock_path):
        raise RunLockHeld("held by another process")

    monkeypatch.setattr(gen_run, "load_env_file", lambda: None)
    monkeypatch.setattr(gen_run, "load_config", lambda path: cfg)
    monkeypatch.setattr(gen_run, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(gen_run, "acquire_run_lock", _raise_lock_held)
    monkeypatch.setattr("sys.argv", ["gen_run"])

    with patch.object(gen_run, "sweep_abandoned_runs") as p_sweep, \
         patch.object(gen_run, "run_generation") as p_run:
        code = gen_run.main()

    assert code == 2
    p_sweep.assert_not_called()
    p_run.assert_not_called()


def test_gen_run_sweep_called_after_lock_acquired_before_run_generation(tmp_path, monkeypatch):
    from src import gen_run

    db_path = Path(tmp_path) / "state.db"
    conn = connect(db_path)
    initialize_schema(conn)
    conn.close()

    cfg = MagicMock()
    cfg.abs_path = lambda rel: Path(tmp_path) / rel
    cfg.paths.logs_dir = "logs"
    cfg.paths.state_db = "state.db"

    call_order: list[str] = []

    def _fake_sweep(repo, cfg, logs_dir):
        call_order.append("sweep")

    def _fake_run_generation(**kwargs):
        call_order.append("run_generation")
        return (True, {"stages": {}})

    monkeypatch.setattr(gen_run, "load_env_file", lambda: None)
    monkeypatch.setattr(gen_run, "load_config", lambda path: cfg)
    monkeypatch.setattr(gen_run, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(gen_run, "sweep_abandoned_runs", _fake_sweep)
    monkeypatch.setattr(gen_run, "run_generation", _fake_run_generation)
    monkeypatch.setattr("sys.argv", ["gen_run"])

    code = gen_run.main()

    assert code == 0
    assert call_order == ["sweep", "run_generation"]


def test_daily_upload_sweep_not_called_when_lock_held(tmp_path, monkeypatch):
    from src import daily_upload

    cfg = MagicMock()
    cfg.abs_path = lambda rel: Path(tmp_path) / rel
    cfg.paths.logs_dir = "logs"
    cfg.paths.state_db = "state.db"
    (Path(tmp_path) / "state.db").write_bytes(b"")

    def _raise_lock_held(_lock_path):
        raise RunLockHeld("held by another process")

    monkeypatch.setattr(daily_upload, "load_env_file", lambda: None)
    monkeypatch.setattr(daily_upload, "load_config", lambda path: cfg)
    monkeypatch.setattr(daily_upload, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(daily_upload, "acquire_run_lock", _raise_lock_held)
    monkeypatch.setattr("sys.argv", ["daily_upload"])

    with patch.object(daily_upload, "sweep_abandoned_runs") as p_sweep, \
         patch.object(daily_upload, "run_today") as p_run:
        code = daily_upload.main()

    assert code == 2
    p_sweep.assert_not_called()
    p_run.assert_not_called()


def test_daily_upload_sweep_called_after_lock_acquired_before_run_today(tmp_path, monkeypatch):
    from src import daily_upload

    db_path = Path(tmp_path) / "state.db"
    conn = connect(db_path)
    initialize_schema(conn)
    conn.close()

    cfg = MagicMock()
    cfg.abs_path = lambda rel: Path(tmp_path) / rel
    cfg.paths.logs_dir = "logs"
    cfg.paths.state_db = "state.db"
    cfg.youtube_quota_ceiling_units = 9000

    call_order: list[str] = []

    def _fake_sweep(repo, cfg, logs_dir):
        call_order.append("sweep")

    def _fake_run_today(**kwargs):
        call_order.append("run_today")
        return ([], 0)

    monkeypatch.setattr(daily_upload, "load_env_file", lambda: None)
    monkeypatch.setattr(daily_upload, "load_config", lambda path: cfg)
    monkeypatch.setattr(daily_upload, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(daily_upload, "sweep_abandoned_runs", _fake_sweep)
    monkeypatch.setattr(daily_upload, "run_today", _fake_run_today)
    monkeypatch.setattr("sys.argv", ["daily_upload", "--dry-run"])

    code = daily_upload.main()

    assert code == 0
    assert call_order == ["sweep", "run_today"]
