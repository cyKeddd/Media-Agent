"""Issue 52 — retention sweeps all output/ copies of uploaded clips."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.retention.cleanup import _safe_unlink, list_output_post_upload_candidates
from src.retention.cleanup import RetentionResult
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    conn = connect(tmp_path / "state.db")
    initialize_schema(conn)
    return Repository(conn)


def _seed_clip(repo, *, clip_id, output_path, updated_at="2026-01-01 00:00:00"):
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, output_path, updated_at) "
        "VALUES (?, NULL, 0, 1, 'h', 't', 'ai_generated', 'uploaded', ?, ?)",
        (clip_id, output_path, updated_at),
    )


def test_finds_duplicate_copies_across_pending_and_approved(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    pending.mkdir(parents=True, exist_ok=True)
    approved.mkdir(parents=True, exist_ok=True)
    name = "2026-06-02__slot_0900__orphan_slug.mp4"
    pending_file = pending / name
    approved_file = approved / name
    pending_file.write_bytes(b"p")
    approved_file.write_bytes(b"a")
    _seed_clip(
        repo,
        clip_id="c1",
        output_path=str(approved_file),
        updated_at="2026-01-01 00:00:00",
    )

    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    pending_paths, approved_paths = list_output_post_upload_candidates(repo, cfg, now=now)

    assert str(pending_file) in pending_paths
    assert str(approved_file) in approved_paths


def test_not_yet_expired_uploaded_clip_not_swept(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    approved = Path(cfg.paths.approved_dir)
    approved.mkdir(parents=True, exist_ok=True)
    f = approved / "fresh.mp4"
    f.write_bytes(b"x")
    _seed_clip(
        repo,
        clip_id="c2",
        output_path=str(f),
        updated_at="2026-06-06 00:00:00",
    )

    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    pending_paths, approved_paths = list_output_post_upload_candidates(repo, cfg, now=now)
    assert pending_paths == []
    assert approved_paths == []


def test_safe_unlink_refuses_outside_root(tmp_path):
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"x")
    result = RetentionResult(dry_run=False)
    ok = _safe_unlink(
        str(outside),
        root=tmp_path,
        result=result,
        logs_dir=Path(tmp_path / "logs"),
    )
    assert ok is False
    assert outside.exists()
