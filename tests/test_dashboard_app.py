"""M2 — FastAPI dashboard smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import create_app


def _make_cfg(tmp_path, output, *, human_review=True):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "alerts.md").write_text("", encoding="utf-8")

    def abs_path(self, p):
        if p.startswith("output"):
            return output if p == "output" else output.parent / p
        if "logs" in p:
            return logs
        return tmp_path / p

    return type("Cfg", (), {
        "abs_path": abs_path,
        "paths": type("P", (), {
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "state_db": "data/state.db",
            "logs_dir": "logs",
        })(),
        "timezone": "Asia/Singapore",
        "human_review": human_review,
        "ai_gen": type("A", (), {
            "per_clip_cost_cents_max": 250,
            "daily_spend_cents_ceiling": 500,
        })(),
    })()


@pytest.fixture
def client(tmp_path, monkeypatch):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    (output / "approved").mkdir(exist_ok=True)
    (output / "rejected").mkdir(exist_ok=True)
    mp4 = pending / "__unscheduled__testclip__slug_abcd.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 100)

    cfg = _make_cfg(tmp_path, output)

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

    app = create_app(cfg=cfg, reader=FakeReader(), output_root=output)
    return TestClient(app), output, mp4


def test_api_view_returns_200_and_shape(client):
    tc, _, _ = client
    resp = tc.get("/api/view")
    assert resp.status_code == 200
    data = resp.json()
    assert "review_queue" in data
    assert "calendar_by_date" in data
    assert "uploaded" in data
    assert "header" in data
    assert "health" in data
    assert data["health"]["overall_status"] in ("healthy", "degraded", "failed")
    assert "generation_run" in data["health"]
    assert "daily_run" in data["health"]
    assert "next_run" in data
    assert "generation_at" in data["next_run"]
    assert "daily_at" in data["next_run"]


def test_video_serves_file_under_output(client):
    tc, output, mp4 = client
    rel = mp4.relative_to(output).as_posix()
    resp = tc.get(f"/api/video/{rel}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("video/")


def test_video_refuses_path_outside_output(client):
    tc, _, _ = client
    resp = tc.get("/api/video/../secret.txt")
    assert resp.status_code in (403, 404)


def test_post_approve_moves_pending_file(tmp_path):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    (output / "approved").mkdir(exist_ok=True)
    (output / "rejected").mkdir(exist_ok=True)
    clip_id = "approve-me"
    mp4 = pending / f"__unscheduled__{clip_id}__slug_x.mp4"
    mp4.write_bytes(b"video")

    cfg = _make_cfg(tmp_path, output, human_review=True)

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

    app = create_app(cfg=cfg, reader=FakeReader(), output_root=output)
    tc = TestClient(app)
    resp = tc.post(
        f"/api/clip/{clip_id}/approve",
        json={"confirm": True},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert (output / "approved" / mp4.name).is_file()
    assert not mp4.exists()


def test_post_approve_refused_when_human_review_off(tmp_path):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    (output / "approved").mkdir(exist_ok=True)
    clip_id = "no-review"
    mp4 = pending / f"__unscheduled__{clip_id}__slug.mp4"
    mp4.write_bytes(b"x")
    cfg = _make_cfg(tmp_path, output, human_review=False)

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

    tc = TestClient(create_app(cfg=cfg, reader=FakeReader(), output_root=output))
    resp = tc.post(f"/api/clip/{clip_id}/approve", json={"confirm": True})
    assert resp.status_code == 403
    assert mp4.exists()
