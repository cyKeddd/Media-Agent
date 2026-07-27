"""Issue 43 — cumulative per-clip OpenRouter spend ceiling (retry-safe)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai_gen.base import GenerationStatus
from src.state import Repository, connect, initialize_schema


def _repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _insert_script(repo: Repository, script_id: str) -> None:
    repo.insert_topic(
        url=f"https://example.com/{script_id}",
        title="Test topic",
        source_feed="https://feed.test/rss",
        fetched_at="2026-05-31T00:00:00Z",
    )
    topic_id = repo.conn.execute("SELECT id FROM topics LIMIT 1").fetchone()["id"]
    repo.insert_script(
        script_id=script_id,
        topic_id=topic_id,
        title="Test script",
        narration="n" * 35,
        shots_json="[]",
        style_suffix="",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-31T00:00:00Z",
    )


def test_script_spend_total_sums_attributed_charges(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 126, provider="openrouter", script_id="script-a")
    repo.quota_record("openrouter", 50, provider="openrouter", script_id="script-b")

    assert repo.quota_script_total("script-a") == 126
    assert repo.quota_script_total("script-b") == 50
    assert repo.quota_script_total("missing") == 0


def test_would_exceed_script_ceiling_before_call(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 126, provider="openrouter", script_id="clip-1")

    assert repo.quota_would_exceed_script("clip-1", 124, 250) is False
    assert repo.quota_would_exceed_script("clip-1", 125, 250) is True


def test_generate_shots_refuses_charge_pushing_lifetime_over_cap(tmp_path):
    from src.ai_gen.runner import generate_shots

    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 200, provider="openrouter", script_id="s1")

    client = MagicMock()
    client.submit.return_value = "ext-1"
    client.wait_for_completion.return_value = MagicMock(
        status=GenerationStatus.SUCCEEDED,
        download_url="http://x/1.mp4",
        cost_cents=126,
        error=None,
    )
    client.download = MagicMock()

    shots = [{"prompt": "p1", "duration_s": 4}]

    with pytest.raises(RuntimeError, match="per_clip_cost_cents_max"):
        generate_shots(
            shots,
            tmp_path / "out",
            client,
            repo=repo,
            script_id="s1",
            per_clip_cost_cents_max=250,
        )

    client.submit.assert_not_called()


def test_generate_shots_reuses_succeeded_jobs_without_billing(tmp_path):
    from src.ai_gen.runner import generate_shots

    repo = _repo(tmp_path)
    script_id = "s1"
    _insert_script(repo, script_id)
    gen_dir = tmp_path / "data" / "ai_gen" / script_id
    gen_dir.mkdir(parents=True)
    existing = gen_dir / "shot_00.mp4"
    existing.write_bytes(b"existing-shot")

    repo.upsert_generation_job(
        job_id="job-0",
        script_id=script_id,
        shot_index=0,
        provider="openrouter_kling",
        prompt="p1",
        duration_s=4,
        status="succeeded",
        output_path=str(existing),
        cost_cents=126,
    )

    client = MagicMock()

    paths = generate_shots(
        [{"prompt": "p1", "duration_s": 4}],
        tmp_path / "dest",
        client,
        repo=repo,
        script_id=script_id,
        per_clip_cost_cents_max=250,
    )

    assert len(paths) == 1
    assert paths[0].read_bytes() == b"existing-shot"
    client.submit.assert_not_called()
    assert repo.quota_script_total(script_id) == 0


def test_retry_after_post_billing_failure_totals_126_not_252(tmp_path):
    """2026-05-31 reverse-aging scenario: Kling bills once, assemble fails, retry reuses."""
    from src.gen_run import _generate_clip

    repo = _repo(tmp_path)
    script_id = "1ec5cbc1"
    _insert_script(repo, script_id)
    gen_dir = tmp_path / "data" / "ai_gen" / script_id
    gen_dir.mkdir(parents=True)
    shot_file = gen_dir / "shot_00.mp4"
    shot_file.write_bytes(b"kling-shot")

    cfg = MagicMock()
    cfg.ai_gen.per_clip_cost_cents_max = 250
    cfg.ai_gen.daily_spend_cents_ceiling = 500
    cfg.ai_gen.weekly_spend_cents_ceiling = 800
    cfg.ai_gen.max_concurrent = 1
    cfg.ai_gen.style_suffix = ""
    cfg.narration.voice = "en-US-GuyNeural"
    cfg.narration.rate = "+10%"
    cfg.narration.pitch = "+0Hz"
    cfg.narration.engine = "edge"
    cfg.narration.kokoro_voice = "am_michael"
    cfg.assembler.crossfade_enabled = False
    cfg.output_resolution = [1080, 1920]
    cfg.nvenc_preset = "p5"
    cfg.nvenc_cq = 23
    cfg.ken_burns_zoom_rate = 0.0015
    cfg.ken_burns_gradient_luma_max = 45
    cfg.ken_burns_gradient_saturation_max = 0.35
    cfg.paths.pending_dir = str(tmp_path / "output" / "pending")
    cfg.abs_path = lambda p: tmp_path / p if not Path(p).is_absolute() else Path(p)

    script = {
        "script_id": script_id,
        "title": "Test clip",
        "narration": "word " * 35,
        "shots": [{"kind": "ai_video", "prompt": "abstract", "duration_s": 4}],
    }
    resolved = [{"kind": "ai_video", "prompt": "abstract", "duration_s": 4}]

    client = MagicMock()
    client.submit.return_value = "ext-1"
    client.wait_for_completion.return_value = MagicMock(
        status=GenerationStatus.SUCCEEDED,
        download_url="http://x/1.mp4",
        cost_cents=126,
        error=None,
    )

    def _download(url, dest):
        dest.write_bytes(b"kling-shot")

    client.download.side_effect = _download

    synth_calls = {"n": 0}

    def _synth_fail(*_a, **_k):
        synth_calls["n"] += 1
        if synth_calls["n"] == 1:
            raise RuntimeError("pitch config bug")
        return None

    def _asm_ok(*_a, **kwargs):
        tmp = kwargs.get("tmp_output")
        if tmp:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(b"x" * 1024)
        return MagicMock(returncode=0, output_size_bytes=1024, stderr="")

    with patch("src.gen_run.OpenRouterKlingClient", return_value=client), \
         patch("src.gen_run.synthesize", side_effect=_synth_fail), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run._run_assembly", side_effect=_asm_ok):
        with pytest.raises(RuntimeError, match="pitch"):
            _generate_clip(
                script, cfg, repo,
                openrouter_api_key="sk-test",
                dry_run=False,
                resolved_shots=resolved,
            )

        assert repo.quota_script_total(script_id) == 126

        _generate_clip(
            script, cfg, repo,
            openrouter_api_key="sk-test",
            dry_run=False,
            resolved_shots=resolved,
        )

    assert repo.quota_script_total(script_id) == 126
    assert client.submit.call_count == 1


def test_daily_ceiling_still_trips_independently(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 480, provider="openrouter", script_id="other")

    assert repo.quota_today_total(provider="openrouter") == 480
    assert repo.quota_would_exceed(30, 500, provider="openrouter") is True
    assert repo.quota_would_exceed(20, 500, provider="openrouter") is False
