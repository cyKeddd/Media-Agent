"""Issue 57 — directed status + scripter narration-only branch."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.scripter.runner import run_stage_b
from src.state import Repository, connect, initialize_schema


@pytest.fixture
def repo(tmp_path):
    conn = connect(tmp_path / "state.db")
    initialize_schema(conn)
    return Repository(conn)


def _cfg(tmp_path):
    s = SimpleNamespace(
        narration_word_count_min=30,
        narration_word_count_max=50,
        banned_tokens=["<<placeholder>>"],
        retry_on_failure=2,
        style_suffix="clean editorial",
        candidate_pool_size=4,
    )
    return SimpleNamespace(
        scripter=s,
        ollama_model="qwen2.5:3b-instruct",
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _good_narration():
    return (
        "OpenAI just shipped a frontier model that tops every public benchmark today. "
        "The release lands with two hundred billion parameters and synthetic chain-of-thought. "
        "Labs everywhere will scramble to match the new reasoning ceiling overnight. "
        "Stay tuned because the next drop might land even sooner."
    )


def test_scripts_awaiting_narration_selects_directed_only(repo):
    repo.conn.execute(
        "INSERT INTO topics (id, url, title, source_feed, fetched_at, status) "
        "VALUES (1, 'u', 'T', 'F', '2026-05-20T10:00:00Z', 'scripted')"
    )
    repo.insert_script(
        script_id="s-directed",
        topic_id=1,
        title="Directed Title",
        narration="",
        shots_json=json.dumps([
            {"kind": "real_image", "entity": "chip", "duration_s": 4},
            {"kind": "ai_video", "prompt": "glow", "duration_s": 4},
            {"kind": "real_image", "entity": "logo", "duration_s": 4},
            {"kind": "ai_video", "prompt": "fade", "duration_s": 4},
        ]),
        style_suffix="suffix",
        ollama_model="nvidia/nemotron-3-ultra:free",
        created_at="2026-05-20T10:00:00Z",
        status="directed",
    )
    repo.insert_script(
        script_id="s-pending",
        topic_id=1,
        title="Pending",
        narration="already done " * 8,
        shots_json="[]",
        style_suffix="suffix",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-20T10:00:00Z",
        status="pending",
    )

    rows = repo.scripts_awaiting_narration()
    assert [r["script_id"] for r in rows] == ["s-directed"]


def test_run_stage_b_fills_directed_narration_and_flips_pending(tmp_path, repo):
    cfg = _cfg(tmp_path)
    repo.conn.execute(
        "INSERT INTO topics (id, url, title, summary, source_feed, fetched_at, status) "
        "VALUES (1, 'u', 'Topic Title', 'summary', 'F', '2026-05-20T10:00:00Z', 'scripted')"
    )
    shots = [
        {"kind": "real_image", "entity": "chip", "duration_s": 4},
        {"kind": "ai_video", "prompt": "glow", "duration_s": 4},
        {"kind": "real_image", "entity": "logo", "duration_s": 4},
        {"kind": "ai_video", "prompt": "fade", "duration_s": 4},
    ]
    repo.insert_script(
        script_id="s1",
        topic_id=1,
        title="Directed Title",
        narration="",
        shots_json=json.dumps(shots),
        style_suffix="suffix",
        ollama_model="nvidia/nemotron-3-ultra:free",
        created_at="2026-05-20T10:00:00Z",
        status="directed",
    )

    def narration_fn(title, shots_json, topic_title, summary):
        return _good_narration()

    def generator_fn(title, summary):
        pytest.fail("full generator should not run for directed backlog")

    run_stage_b(
        cfg, repo, [],
        generator_fn=generator_fn,
        narration_fn=narration_fn,
    )
    row = repo.get_script("s1")
    assert row["status"] == "pending"
    assert row["narration"]
    assert json.loads(row["shots_json"]) == shots


def test_run_stage_b_still_generates_full_script_for_unscripted_topic(tmp_path, repo):
    cfg = _cfg(tmp_path)
    repo.conn.execute(
        "INSERT INTO topics (id, url, title, summary, source_feed, fetched_at, status) "
        "VALUES (2, 'u2', 'Fresh Topic', NULL, 'F', '2026-05-20T10:00:00Z', 'unscripted')"
    )
    topics = [{"id": 2, "title": "Fresh Topic", "summary": None}]

    def generator_fn(title, summary):
        return {
            "title": "Fresh Topic",
            "narration": _good_narration(),
            "shots": [
                {"kind": "real_image", "entity": "phone", "duration_s": 4},
                {"kind": "ai_video", "prompt": "pulse", "duration_s": 4},
                {"kind": "real_image", "entity": "gpu", "duration_s": 4},
                {"kind": "ai_video", "prompt": "beam", "duration_s": 4},
            ],
            "style_notes": "clean",
        }

    run_stage_b(cfg, repo, topics, generator_fn=generator_fn, narration_fn=lambda *a, **k: "")
    row = repo.conn.execute("SELECT * FROM scripts WHERE topic_id=2").fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["narration"]
