"""Issue 62 — rolling 7x24h OpenRouter weekly spend ceiling (INV-1).

Covers:
  - repository-level rolling-window predicate (boundary + window-edge cases)
  - gen_run refuses a billable call that would cross the ceiling: zero
    provider calls, a spend_cap_reached alert, and a success=1 'capped' run.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.policy_gate.evaluator import PolicyVerdict
from src.state import Repository, connect, initialize_schema


def _repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _utc_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ---------------------------------------------------------------------------
# Repository-level predicate
# ---------------------------------------------------------------------------


def test_rolling_week_total_excludes_spend_8_days_ago(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record(
        "openrouter", 500, provider="openrouter", recorded_at=_utc_ago(8)
    )
    assert repo.quota_rolling_week_total(provider="openrouter") == 0


def test_rolling_week_total_includes_spend_6_days_ago(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record(
        "openrouter", 500, provider="openrouter", recorded_at=_utc_ago(6)
    )
    assert repo.quota_rolling_week_total(provider="openrouter") == 500


def test_boundary_799_plus_1_allowed_799_plus_2_refused(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record(
        "openrouter", 799, provider="openrouter", recorded_at=_utc_ago(1)
    )
    assert repo.quota_would_exceed_week(1, 800, provider="openrouter") is False
    assert repo.quota_would_exceed_week(2, 800, provider="openrouter") is True


def test_would_exceed_week_defaults_to_openrouter_provider(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("videos.insert", 400, provider="youtube", recorded_at=_utc_ago(1))
    # youtube spend must not count against the OpenRouter weekly ceiling.
    assert repo.quota_would_exceed_week(800, 800) is False


# ---------------------------------------------------------------------------
# gen_run integration — refused before any provider call
# ---------------------------------------------------------------------------


class _AiGenStub:
    model = "kwaivgi/kling-v3.0-std"
    per_clip_cost_cents_max = 150
    daily_spend_cents_ceiling = 300
    weekly_spend_cents_ceiling = 800
    still_cost_cents_max = 5
    still_clip_cost_cents_max = 20
    max_concurrent = 2
    shot_duration_s = 5
    style_suffix = "editorial, 9:16"


class _NarrationStub:
    engine = "edge"
    kokoro_voice = "am_michael"
    voice = "en-US-GuyNeural"
    rate = "+10%"
    pitch = "+0Hz"


class _AssemblerStub:
    crossfade_enabled = False
    crossfade_duration_s = 0.25


class _ImageFetchStub:
    sources = ["logo", "wikimedia", "openverse", "web"]
    min_resolution = 512
    max_candidates_per_source = 5
    web_fallback_enabled = True
    living_person_patterns = ["portrait of", "photo of"]


class _Paths:
    def __init__(self, tmp_path):
        logs = Path(tmp_path) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.logs_dir = str(logs)
        self.state_db = str(Path(tmp_path) / "state.db")
        self.pending_dir = str(Path(tmp_path) / "output" / "pending")
        self.rejected_dir = str(Path(tmp_path) / "output" / "rejected")
        self.images_dir = str(Path(tmp_path) / "data" / "images")


class _GenStubConfig:
    def __init__(self, tmp_path):
        self.project_root = Path(tmp_path)
        self.paths = _Paths(tmp_path)
        self.ai_gen = _AiGenStub()
        self.narration = _NarrationStub()
        self.assembler = _AssemblerStub()
        self.image_fetch = _ImageFetchStub()
        self.clips_per_day = 2
        self.days_per_run = 7
        self.upload_slots = ["09:00", "17:00"]
        self.timezone = "Asia/Singapore"
        self.human_review = True
        self.output_resolution = [1080, 1920]
        self.ollama_model = "qwen2.5:3b-instruct"
        self.output_fps = 30
        self.nvenc_preset = "p5"
        self.nvenc_cq = 23
        self.loudness_target_lufs = -14.0
        self.music_volume_db = -15.0
        self.blurred_bg_sigma = 20
        self.ken_burns_zoom_rate = 0.0015

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def _ai_video_script(script_id: str) -> dict:
    return {
        "script_id": script_id,
        "title": "T1",
        "narration": "n" * 35,
        "shots": [{"kind": "ai_video", "prompt": "abstract data flow", "duration_s": 4}],
    }


def test_gen_run_refuses_call_that_would_cross_weekly_ceiling(tmp_path):
    """Repo already at 799c: a 67c-projected shot would cross 800c -> refused,
    zero provider calls, spend_cap_reached alert, run finishes success=1
    with a capped summary."""
    from src.gen_run import run_generation

    repo = _repo(tmp_path)
    repo.quota_record(
        "openrouter", 799, provider="openrouter",
        recorded_at=_utc_ago(1),
    )
    cfg = _GenStubConfig(tmp_path)

    fake_scripts = [_ai_video_script("s1")]

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run.generate_shots") as p_gen, \
         patch("src.gen_run.build_video_provider") as p_client, \
         patch("src.gen_run.synthesize") as p_synth:
        success, summary = run_generation(
            repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
        )

    assert success is True
    assert summary.get("capped") is True

    # Zero provider calls: the client is never even constructed (Issue 67 —
    # build_video_provider is the config-driven seam), and generate_shots
    # (which would call client.submit) is never invoked.
    p_client.assert_not_called()
    p_gen.assert_not_called()
    p_synth.assert_not_called()

    alerts = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "spend_cap_reached" in alerts

    row = repo.conn.execute(
        "SELECT success FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["success"] == 1

    # The refused call must not have recorded any additional spend.
    assert repo.quota_rolling_week_total(provider="openrouter") == 799


def test_gen_run_allows_call_under_the_ceiling(tmp_path):
    """Repo at 0c: a 67c-projected shot is well under 800c -> proceeds normally."""
    from src.gen_run import run_generation

    repo = _repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    fake_scripts = [_ai_video_script("s1")]
    fake_shot = Path(tmp_path) / "shot_00.mp4"
    fake_shot.write_bytes(b"fake")

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run.generate_shots", return_value=[fake_shot]) as p_gen, \
         patch("src.gen_run.build_video_provider") as p_client, \
         patch("src.gen_run.synthesize") as p_synth, \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", return_value=MagicMock(returncode=0, output_size_bytes=1024)):
        success, summary = run_generation(
            repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
        )

    assert success is True
    assert not summary.get("capped")
    p_client.assert_called_once()
    p_gen.assert_called_once()
