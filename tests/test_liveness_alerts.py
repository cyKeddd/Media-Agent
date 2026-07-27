"""Issue 61 — liveness alert (INV-5).

Covers:
  - config_loader: `liveness_stale_days` surfaces with default 7, is
    configurable, and the committed config.yaml carries it explicitly.
  - src.observability.check_liveness:
      * a Clip rendered within the window -> no alert
      * no Clip rendered within the window -> `liveness_stalled` alert
        naming the elapsed days and the last rendered Clip
      * no Clip ever rendered -> alert (never silently skipped)
      * the alert fires at most once per UTC calendar day (heartbeat, not
        per-invocation)
  - src.gen_run.main / src.daily_upload.main call check_liveness inside
    the run-lock block, alongside sweep_abandoned_runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config_loader import load_config
from src.observability import check_liveness
from src.observability.liveness import LIVENESS_STALLED
from src.state import Repository, connect, initialize_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_repo(tmp_path) -> Repository:
    db = Path(tmp_path) / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _insert_rendered_clip(
    repo: Repository,
    *,
    clip_id: str,
    title: str = "Some Clip",
    days_ago: float | None = None,
    created_at: str | None = None,
) -> None:
    """Insert a `clips` row the way _persist_rendered_clip does — status
    'rendered' at creation. Pass either `days_ago` (relative to wall-clock
    now — fine when the test also calls check_liveness with its default
    now=datetime.now()) or an explicit `created_at` string (for tests that
    also pass a fixed `now=` to check_liveness, so both sides share one
    deterministic reference point)."""
    if created_at is None:
        assert days_ago is not None, "must pass days_ago or created_at"
        created_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    repo.conn.execute(
        "INSERT INTO clips "
        "(clip_id, video_id, start_s, end_s, hook, suggested_title, "
        " title_slug, selection_method, content_kind, status, created_at, updated_at) "
        "VALUES (?, NULL, 0, 1, 'hook', ?, 'slug', 'ai_generated', "
        " 'ai_generated', 'rendered', ?, ?)",
        (clip_id, title, created_at, created_at),
    )


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


# ---------------------------------------------------------------------------
# config_loader: liveness_stale_days
# ---------------------------------------------------------------------------


def test_liveness_stale_days_defaults_to_7(tmp_path):
    cfg_path = _write_yaml(tmp_path, _minimal_config_dict())
    cfg = load_config(cfg_path)
    assert cfg.liveness_stale_days == 7


def test_liveness_stale_days_configurable(tmp_path):
    payload = _minimal_config_dict()
    payload["liveness_stale_days"] = 3
    cfg_path = _write_yaml(tmp_path, payload)
    cfg = load_config(cfg_path)
    assert cfg.liveness_stale_days == 3


def test_real_config_yaml_has_liveness_stale_days():
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
    assert cfg.liveness_stale_days == 7


# ---------------------------------------------------------------------------
# check_liveness — within window -> no alert
# ---------------------------------------------------------------------------


def test_no_alert_when_clip_rendered_within_window(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="c1", days_ago=1)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts_path = logs_dir / "alerts.md"
    if alerts_path.exists():
        assert LIVENESS_STALLED not in alerts_path.read_text(encoding="utf-8")


def test_no_alert_exactly_at_window_boundary(tmp_path):
    """A Clip rendered exactly `liveness_stale_days` ago is still within
    the window (elapsed <= threshold, not strictly less). Both the
    created_at fixture and `now` are pinned to the same fixed reference so
    the assertion isn't at the mercy of wall-clock execution drift."""
    repo = _new_repo(tmp_path)
    rendered_at = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
    now = rendered_at + timedelta(days=7)
    _insert_rendered_clip(
        repo, clip_id="c1", created_at=rendered_at.strftime("%Y-%m-%d %H:%M:%S")
    )
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir, now=now)

    alerts_path = logs_dir / "alerts.md"
    if alerts_path.exists():
        assert LIVENESS_STALLED not in alerts_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# check_liveness — stale -> alert, naming elapsed days + last Clip
# ---------------------------------------------------------------------------


def test_alert_when_no_clip_rendered_within_window(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="clip-stale", title="Stale Clip", days_ago=10)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert LIVENESS_STALLED in alerts


def test_alert_names_elapsed_days_and_last_clip(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="clip-stale-42", title="The Stale One", days_ago=10)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert "clip-stale-42" in alerts
    assert "10.0 days" in alerts


def test_alert_when_no_clip_ever_rendered(tmp_path):
    repo = _new_repo(tmp_path)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert LIVENESS_STALLED in alerts
    assert "no Clip has ever been rendered" in alerts


def test_multiple_clips_uses_the_most_recently_rendered(tmp_path):
    """A stale first clip followed by a fresh later clip must NOT alert —
    the query must pick the most recent render, not the first row."""
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="old", days_ago=30)
    _insert_rendered_clip(repo, clip_id="fresh", days_ago=1)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts_path = logs_dir / "alerts.md"
    if alerts_path.exists():
        assert LIVENESS_STALLED not in alerts_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# check_liveness — at most once per calendar day
# ---------------------------------------------------------------------------


def test_alert_fires_at_most_once_per_calendar_day(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="clip-stale", days_ago=10)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)
    check_liveness(repo, cfg, logs_dir)
    check_liveness(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert alerts.count(LIVENESS_STALLED) == 1


def test_alert_fires_again_on_a_new_calendar_day(tmp_path):
    """A stall spanning multiple days produces a daily heartbeat: one
    alert per UTC calendar day, not a single alert forever."""
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="clip-stale", created_at="2026-07-01 00:00:00")
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    day1 = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 7, 21, 10, 0, 0, tzinfo=timezone.utc)

    check_liveness(repo, cfg, logs_dir, now=day1)
    check_liveness(repo, cfg, logs_dir, now=day1)  # same day -> no second row
    check_liveness(repo, cfg, logs_dir, now=day2)  # new day -> heartbeat fires again

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert alerts.count(LIVENESS_STALLED) == 2


# ---------------------------------------------------------------------------
# INV-6 regression guard — no alert text may contain the OpenRouter key
# ---------------------------------------------------------------------------


def test_liveness_alert_never_contains_a_key_shaped_value(tmp_path):
    repo = _new_repo(tmp_path)
    _insert_rendered_clip(repo, clip_id="clip-stale", days_ago=10)
    logs_dir = Path(tmp_path) / "logs"

    cfg = MagicMock()
    cfg.liveness_stale_days = 7

    check_liveness(repo, cfg, logs_dir)

    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert "sk-or-v1-" not in alerts


# ---------------------------------------------------------------------------
# Entry points call check_liveness inside the run-lock block
# ---------------------------------------------------------------------------


def test_gen_run_calls_check_liveness_after_lock_acquired(tmp_path, monkeypatch):
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

    def _fake_liveness(repo, cfg, logs_dir):
        call_order.append("liveness")

    def _fake_run_generation(**kwargs):
        call_order.append("run_generation")
        return (True, {"stages": {}})

    monkeypatch.setattr(gen_run, "load_env_file", lambda: None)
    monkeypatch.setattr(gen_run, "load_config", lambda path: cfg)
    monkeypatch.setattr(gen_run, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(gen_run, "sweep_abandoned_runs", _fake_sweep)
    monkeypatch.setattr(gen_run, "check_liveness", _fake_liveness)
    monkeypatch.setattr(gen_run, "run_generation", _fake_run_generation)
    monkeypatch.setattr("sys.argv", ["gen_run"])

    code = gen_run.main()

    assert code == 0
    assert call_order == ["sweep", "liveness", "run_generation"]


def test_daily_upload_calls_check_liveness_after_lock_acquired(tmp_path, monkeypatch):
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

    def _fake_liveness(repo, cfg, logs_dir):
        call_order.append("liveness")

    def _fake_run_today(**kwargs):
        call_order.append("run_today")
        return ([], 0)

    monkeypatch.setattr(daily_upload, "load_env_file", lambda: None)
    monkeypatch.setattr(daily_upload, "load_config", lambda path: cfg)
    monkeypatch.setattr(daily_upload, "setup_logging", lambda logs_dir: None)
    monkeypatch.setattr(daily_upload, "sweep_abandoned_runs", _fake_sweep)
    monkeypatch.setattr(daily_upload, "check_liveness", _fake_liveness)
    monkeypatch.setattr(daily_upload, "run_today", _fake_run_today)
    monkeypatch.setattr("sys.argv", ["daily_upload", "--dry-run"])

    code = daily_upload.main()

    assert code == 0
    assert call_order == ["sweep", "liveness", "run_today"]
