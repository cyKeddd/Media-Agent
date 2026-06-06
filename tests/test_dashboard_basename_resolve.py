"""Issue 53 — dashboard locates clips by output_path basename."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.dashboard.scanner import scan_output_dirs
from src.dashboard.view_model import ReviewStage, build_dashboard_view

from tests.test_dashboard_view_model import FakeClip, FakeReader, _caps

SGT = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=SGT)


def test_scanner_by_basename_prefers_approved(tmp_path):
    root = tmp_path / "output"
    for sub in ("pending", "approved", "rejected", "dry_run"):
        (root / sub).mkdir(parents=True)
    name = "2026-06-02__slot_0900__real_slug.mp4"
    (root / "pending" / name).write_bytes(b"p")
    approved = root / "approved" / name
    approved.write_bytes(b"a")

    scan = scan_output_dirs(root)

    assert scan.by_basename[name] == ("approved", approved)


def test_resolver_matches_basename_when_title_slug_null(tmp_path):
    root = tmp_path / "output"
    for sub in ("pending", "approved", "rejected", "dry_run"):
        (root / sub).mkdir(parents=True)
    filename = "2026-06-02__slot_0900__baked_slug_ab12.mp4"
    (root / "approved" / filename).write_bytes(b"x")
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id="clipX",
                title_slug=None,
                suggested_title="Different Title Altogether",
                publish_at_utc="2026-06-04T01:00:00Z",
                output_path=str(root / "pending" / filename),
            )
        ]
    )
    scan = scan_output_dirs(root)
    view = build_dashboard_view(
        reader, scan, now=NOW, tz=SGT, ai_gen=_caps(), output_root=root,
    )

    assert view.clips[0].file_subdir == "approved"
    assert view.clips[0].review_stage == ReviewStage.approved_scheduled
