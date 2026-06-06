"""Issue 51 — daily_upload writes a SQLite runs row for dashboard health."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.daily_upload import build_daily_run_summary, run_today
from src.dashboard.run_reader import latest_run_per_kind
from src.dashboard.view_model import _run_tile
from src.state import Repository, connect, initialize_schema
from src.uploader.runner import UploadOutcome, UploadResult

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _seed_video(repo: Repository) -> None:
    repo.conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("v1", "t", "c", 600, 1, "2026-04-01T00:00:00Z", "movies", 1.0, "downloaded"),
    )


def _seed_clip(
    repo: Repository,
    *,
    clip_id: str,
    status: str = "approved",
    publish_at_utc: str = "2026-05-03T01:00:00Z",
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, "v1", 30.0, 60.0, "hook", "title", "transcript_only",
         status, publish_at_utc),
    )


def test_build_daily_run_summary_uploaded_count():
    results = [
        UploadResult(clip_id="a", outcome=UploadOutcome.uploaded, youtube_video_id="x"),
        UploadResult(clip_id="b", outcome=UploadOutcome.api_rejected, reason="bad"),
        UploadResult(clip_id="c", outcome=UploadOutcome.uploaded, youtube_video_id="y"),
    ]
    assert build_daily_run_summary(results=results) == {"uploaded": 2}


def test_build_daily_run_summary_no_candidates():
    assert build_daily_run_summary(no_candidates=True) == {"message": "no_candidates"}


def test_build_daily_run_summary_error():
    assert build_daily_run_summary(error="orphan_reconcile_required") == {
        "error": "orphan_reconcile_required",
    }


def test_run_today_writes_daily_run_row_on_success(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="c1")

    def _ok_orphans(*, repo, cfg):
        return (True, [])

    def _upload(**kwargs):
        return UploadResult(
            clip_id=kwargs["clip_id"],
            outcome=UploadOutcome.uploaded,
            youtube_video_id="yt",
        )

    with patch("src.uploader.runner.reconcile_orphans", _ok_orphans), \
         patch("src.uploader.runner.upload_one_clip", _upload):
        run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            dry_run=False,
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )

    row = repo.conn.execute(
        "SELECT kind, success, summary_json, finished_at FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["kind"] == "daily"
    assert row["success"] == 1
    assert row["finished_at"] is not None
    summary = json.loads(row["summary_json"])
    assert summary == {"uploaded": 1}


def test_run_today_writes_no_candidates_run_row(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)

    def _ok_orphans(*, repo, cfg):
        return (True, [])

    with patch("src.uploader.runner.reconcile_orphans", _ok_orphans):
        run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            dry_run=False,
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )

    row = repo.conn.execute("SELECT success, summary_json FROM runs").fetchone()
    assert row["success"] == 1
    assert json.loads(row["summary_json"]) == {"message": "no_candidates"}


def test_run_today_orphan_abort_writes_failed_run_row(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="x")

    def _bad_orphans(*, repo, cfg):
        return (False, ["orphan_reconcile_required: 1 inconsistent marker"])

    with patch("src.uploader.runner.reconcile_orphans", _bad_orphans):
        _, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            dry_run=False,
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 4
    row = repo.conn.execute("SELECT success, summary_json FROM runs").fetchone()
    assert row["success"] == 0
    assert "error" in json.loads(row["summary_json"])


def test_run_today_dry_run_writes_no_run_row(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="c1")

    def _ok_orphans(*, repo, cfg):
        return (True, [])

    def _upload(**kwargs):
        return UploadResult(clip_id=kwargs["clip_id"], outcome=UploadOutcome.dry_run)

    with patch("src.uploader.runner.reconcile_orphans", _ok_orphans), \
         patch("src.uploader.runner.upload_one_clip", _upload):
        run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            dry_run=True,
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )

    count = repo.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert count == 0
    runs_md = (Path(cfg.paths.logs_dir) / "runs.md").read_text(encoding="utf-8")
    assert "| daily |" in runs_md


def test_run_today_exception_finalizes_run_row_then_reraises(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="c1")

    def _ok_orphans(*, repo, cfg):
        return (True, [])

    def _boom(**kwargs):
        raise RuntimeError("oauth exploded")

    with patch("src.uploader.runner.reconcile_orphans", _ok_orphans), \
         patch("src.uploader.runner.upload_one_clip", _boom):
        with pytest.raises(RuntimeError, match="oauth exploded"):
            run_today(
                repo=repo, cfg=cfg, ledger=object(), youtube=object(),
                dry_run=False,
                now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
            )

    row = repo.conn.execute("SELECT success, summary_json, finished_at FROM runs").fetchone()
    assert row["success"] == 0
    assert row["finished_at"] is not None
    assert "oauth exploded" in json.loads(row["summary_json"])["error"]


def test_dashboard_daily_tile_from_written_run(tmp_path):
    repo = _new_repo(tmp_path)
    run_id = repo.start_run("daily")
    repo.finish_run(run_id, success=True, summary_json=json.dumps({"uploaded": 2}))

    snap = latest_run_per_kind(repo.conn)["daily"]
    tile = _run_tile(snap)
    assert tile.label == "OK"
    assert tile.detail == "uploaded=2"

    run_id2 = repo.start_run("daily")
    repo.finish_run(run_id2, success=True, summary_json=json.dumps({"message": "no_candidates"}))
    snap2 = latest_run_per_kind(repo.conn)["daily"]
    assert _run_tile(snap2).detail == "no_candidates"

    run_id3 = repo.start_run("daily")
    repo.finish_run(run_id3, success=False, summary_json=json.dumps({"error": "boom"}))
    snap3 = latest_run_per_kind(repo.conn)["daily"]
    tile3 = _run_tile(snap3)
    assert tile3.label == "Failed"
    assert tile3.error == "boom"

    run_id4 = repo.start_run("daily")
    snap4 = latest_run_per_kind(repo.conn)["daily"]
    tile4 = _run_tile(snap4)
    assert tile4.label == "In progress"
