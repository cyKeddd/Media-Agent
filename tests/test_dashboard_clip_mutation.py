"""Issues 55–56 — Operator override plans and endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import create_app
from src.dashboard.clip_mutation import (
    MutationRefusal,
    apply_mutation_plan,
    plan_edit_title,
    plan_reschedule,
)
from src.observability.run_lock import RunLockHeld
from src.state import Repository, connect, initialize_schema
from src.uploader.templater import build_title

from tests.test_dashboard_app import _make_cfg

SGT = ZoneInfo("Asia/Singapore")


def _repo(tmp_path) -> Repository:
    conn = connect(tmp_path / "state.db", check_same_thread=False)
    initialize_schema(conn)
    return Repository(conn)


def _clip_row(**kwargs):
    base = {
        "clip_id": "clip1",
        "youtube_video_id": None,
        "output_path": None,
        "suggested_title": "Old Title",
        "hook": "Old hook",
        "status": "quality_pass",
        "publish_at_utc": "2026-06-10T01:00:00Z",
        "publish_slot_local": "2026-06-10 09:00",
        "title_slug": "old_slug_abcd",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_plan_reschedule_refuses_published():
    row = _clip_row(youtube_video_id="yt123", output_path="output/pending/x.mp4")
    now = datetime(2026, 6, 6, 10, 0, tzinfo=SGT)
    result = plan_reschedule(
        row,
        datetime(2026, 6, 8, 10, 0, tzinfo=SGT),
        SGT,
        now,
    )
    assert isinstance(result, MutationRefusal)
    assert result.code == "published"


def test_plan_reschedule_refuses_too_soon():
    row = _clip_row(output_path="output/pending/2026-06-06__slot_1200__slug.mp4")
    now = datetime(2026, 6, 6, 10, 15, tzinfo=SGT)
    result = plan_reschedule(
        row,
        datetime(2026, 6, 6, 10, 25, tzinfo=SGT),
        SGT,
        now,
    )
    assert isinstance(result, MutationRefusal)
    assert result.code == "too_soon"


def test_plan_reschedule_warns_on_collision():
    row = _clip_row(output_path="output/pending/2026-06-06__slot_1200__slug.mp4")
    now = datetime(2026, 6, 6, 8, 0, tzinfo=SGT)
    result = plan_reschedule(
        row,
        datetime(2026, 6, 8, 10, 0, tzinfo=SGT),
        SGT,
        now,
        collision_clip_ids=["other"],
    )
    assert result.warning is not None
    assert "collision" in result.warning


def test_plan_edit_title_sets_hook_and_slug():
    row = _clip_row(output_path="output/pending/2026-06-06__slot_0900__old_slug.mp4")
    plan = plan_edit_title(row, "Brand New Title Here", "clip1")
    assert plan.db_updates["suggested_title"] == "Brand New Title Here"
    assert plan.db_updates["hook"] == "Brand New Title Here"
    assert build_title(plan.db_updates["hook"], plan.db_updates["suggested_title"]).startswith(
        "Brand New Title Here"
    )


def test_apply_mutation_db_first_then_rename(tmp_path):
    repo = _repo(tmp_path)
    pending = tmp_path / "output" / "pending"
    pending.mkdir(parents=True)
    src = pending / "2026-06-06__slot_0900__old_slug.mp4"
    src.write_bytes(b"video")
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, output_path) "
        "VALUES (?, NULL, 0, 1, ?, ?, 'ai_generated', 'quality_pass', ?)",
        ("clip1", "Old hook", "Old Title", str(src)),
    )
    dest = pending / "2026-06-06__slot_0900__new_slug.mp4"
    from src.dashboard.clip_mutation import MutationPlan

    plan = MutationPlan(
        clip_id="clip1",
        db_updates={
            "hook": "New",
            "suggested_title": "New",
            "title_slug": "new_slug",
            "output_path": str(dest),
        },
        from_path=src,
        to_path=dest,
    )
    apply_mutation_plan(repo, plan)
    row = repo.get_clip("clip1")
    assert row["output_path"] == str(dest)
    assert dest.exists()
    assert not src.exists()


@pytest.fixture
def mutation_client(tmp_path):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    (output / "approved").mkdir(exist_ok=True)
    mp4 = pending / "2026-06-06__slot_0900__slug_test.mp4"
    mp4.write_bytes(b"video")
    cfg = _make_cfg(tmp_path, output)
    repo = _repo(tmp_path)
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc, output_path) "
        "VALUES (?, NULL, 0, 1, ?, ?, 'ai_generated', 'quality_pass', ?, ?)",
        ("clip1", "hook", "Title", "2026-06-10T01:00:00Z", str(mp4)),
    )

    class FakeReader:
        def list_dashboard_clips(self):
            return []

        def count_topics_by_status(self, status):
            return 0

        def quota_today_total(self, *, provider=None):
            return 0

        def quota_week_total(self, *, provider=None):
            return 0

        def quota_script_total(self, script_id):
            return 0

        def latest_runs(self):
            from src.dashboard.run_reader import RunSnapshot
            return {
                "generation": RunSnapshot(kind="generation", present=False),
                "daily": RunSnapshot(kind="daily", present=False),
            }

    app = create_app(cfg=cfg, reader=FakeReader(), repo=repo, output_root=output)
    return TestClient(app), repo, mp4


def test_reschedule_endpoint_409_when_lock_held(mutation_client):
    from contextlib import contextmanager

    tc, _, _ = mutation_client

    @contextmanager
    def _held(_path):
        raise RunLockHeld("held")
        yield

    with patch("src.dashboard.app.acquire_run_lock", _held):
        resp = tc.post(
            "/api/clip/clip1/reschedule",
            json={"confirm": True, "publish_at_local": "2026-06-08T10:00:00+08:00"},
        )
    assert resp.status_code == 409


def test_edit_title_endpoint_403_when_human_review_off(tmp_path):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    mp4 = pending / "2026-06-06__slot_0900__slug.mp4"
    mp4.write_bytes(b"x")
    cfg = _make_cfg(tmp_path, output, human_review=False)
    repo = _repo(tmp_path)
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, output_path) VALUES (?, NULL, 0, 1, ?, ?, 'ai_generated', 'quality_pass', ?)",
        ("clip1", "h", "t", str(mp4)),
    )

    class FakeReader:
        def list_dashboard_clips(self):
            return []

        def count_topics_by_status(self, status):
            return 0

        def quota_today_total(self, *, provider=None):
            return 0

        def quota_week_total(self, *, provider=None):
            return 0

        def quota_script_total(self, script_id):
            return 0

        def latest_runs(self):
            from src.dashboard.run_reader import RunSnapshot
            return {
                "generation": RunSnapshot(kind="generation", present=False),
                "daily": RunSnapshot(kind="daily", present=False),
            }

    tc = TestClient(create_app(cfg=cfg, reader=FakeReader(), repo=repo, output_root=output))
    resp = tc.post(
        "/api/clip/clip1/edit-title",
        json={"confirm": True, "title": "New Title"},
    )
    assert resp.status_code == 403
