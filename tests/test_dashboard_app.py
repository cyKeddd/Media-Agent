"""M2 — FastAPI dashboard smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    output = tmp_path / "output"
    pending = output / "pending"
    pending.mkdir(parents=True)
    mp4 = pending / "__unscheduled__testclip__slug_abcd.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 100)

    cfg = type("Cfg", (), {
        "abs_path": lambda self, p: output if p.startswith("output") else tmp_path / p,
        "paths": type("P", (), {
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "state_db": "data/state.db",
        })(),
        "timezone": "Asia/Singapore",
        "ai_gen": type("A", (), {
            "per_clip_cost_cents_max": 250,
            "daily_spend_cents_ceiling": 500,
        })(),
    })()

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
