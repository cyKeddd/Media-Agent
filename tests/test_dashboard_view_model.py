"""M1 — dashboard view-model (Review stage, queue, calendar, uploaded, header)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.dashboard.scanner import ScanResult
from src.dashboard.view_model import (
    ReviewStage,
    build_dashboard_view,
)
from src.editor.slug import title_slug


SGT = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=SGT)


@dataclass
class FakeClip:
    clip_id: str
    hook: str = "Hook text here"
    suggested_title: str = "Test Title"
    title_slug: str | None = None
    content_kind: str = "ai_generated"
    script_id: str | None = None
    status: str = "quality_pass"
    publish_at_utc: str | None = None
    youtube_video_id: str | None = None
    script_title: str | None = None
    script_narration: str | None = None
    shots_json: str | None = None


@dataclass
class FakeReader:
    clips: list[FakeClip] = field(default_factory=list)
    unscripted_count: int = 0
    spend_today: int = 0
    spend_week: int = 0
    script_totals: dict[str, int] = field(default_factory=dict)

    def list_dashboard_clips(self) -> list[FakeClip]:
        return list(self.clips)

    def count_topics_by_status(self, status: str) -> int:
        if status == "unscripted":
            return self.unscripted_count
        return 0

    def quota_today_total(self, *, provider: str | None = None) -> int:
        return self.spend_today

    def quota_week_total(self, *, provider: str | None = None) -> int:
        return self.spend_week

    def quota_script_total(self, script_id: str) -> int:
        return self.script_totals.get(script_id, 0)


def _caps():
    return SimpleNamespace(per_clip_cost_cents_max=250, daily_spend_cents_ceiling=500)


def _scan(root: Path, *, pending: str | None = None, approved: str | None = None) -> ScanResult:
    for sub in ("pending", "approved", "rejected", "dry_run"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    by_clip_id: dict[str, tuple[str, Path]] = {}
    by_slug: dict[str, tuple[str, Path]] = {}
    if pending:
        p = root / "pending" / pending
        p.write_bytes(b"x")
        if pending.startswith("__unscheduled__"):
            parts = pending.removeprefix("__unscheduled__").removesuffix(".mp4").split("__", 1)
            by_clip_id[parts[0]] = ("pending", p)
            if len(parts) > 1:
                by_slug[parts[1]] = ("pending", p)
        else:
            slug = pending.split("__", 2)[-1].removesuffix(".mp4")
            by_slug[slug] = ("pending", p)
    if approved:
        p = root / "approved" / approved
        p.write_bytes(b"x")
        slug = approved.split("__", 2)[-1].removesuffix(".mp4")
        by_slug[slug] = ("approved", p)
    return ScanResult(by_clip_id=by_clip_id, by_slug=by_slug)


def test_pending_file_is_awaiting_review(tmp_path):
    clip_id = "clipA"
    slug = title_slug("Test Title", clip_id)
    reader = FakeReader(clips=[FakeClip(clip_id=clip_id, title_slug=slug)])
    scan = _scan(tmp_path, pending=f"__unscheduled__{clip_id}__{slug}.mp4")

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.clips[0].review_stage == ReviewStage.awaiting_review
    assert len(view.review_queue) == 1
    assert view.review_queue[0].clip_id == clip_id


def test_approved_with_publish_is_scheduled(tmp_path):
    clip_id = "clipB"
    slug = title_slug("Scheduled", clip_id)
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id=clip_id,
                title_slug=slug,
                publish_at_utc="2026-06-04T01:00:00Z",
            )
        ]
    )
    scan = _scan(tmp_path, approved=f"2026-06-04__slot_0900__{slug}.mp4")

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.clips[0].review_stage == ReviewStage.approved_scheduled
    assert len(view.review_queue) == 0


def test_youtube_id_is_published(tmp_path):
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id="clipC",
                youtube_video_id="yt123",
                publish_at_utc="2026-05-28T01:00:00Z",
            )
        ]
    )
    scan = ScanResult(by_clip_id={}, by_slug={})

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.clips[0].review_stage == ReviewStage.published


def test_rejected_status(tmp_path):
    reader = FakeReader(clips=[FakeClip(clip_id="clipD", status="rejected_quality")])
    scan = ScanResult(by_clip_id={}, by_slug={})

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.clips[0].review_stage == ReviewStage.rejected


def test_stale_output_path_ignored_uses_scanner(tmp_path):
    clip_id = "clipE"
    slug = title_slug("Stale path", clip_id)
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id=clip_id,
                title_slug=slug,
                publish_at_utc="2026-06-04T01:00:00Z",
            )
        ]
    )
    scan = _scan(tmp_path, approved=f"2026-06-04__slot_0900__{slug}.mp4")

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.clips[0].review_stage == ReviewStage.approved_scheduled
    assert view.clips[0].file_subdir == "approved"


def test_calendar_grouped_by_local_date(tmp_path):
    clip_id = "clipF"
    slug = title_slug("Cal", clip_id)
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id=clip_id,
                title_slug=slug,
                suggested_title="Cal",
                publish_at_utc="2026-06-04T01:00:00Z",  # 09:00 SGT
            )
        ]
    )
    scan = _scan(tmp_path, pending=f"2026-06-04__slot_0900__{slug}.mp4")

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert "2026-06-04" in view.calendar_by_date
    entry = view.calendar_by_date["2026-06-04"][0]
    assert entry.clip_id == clip_id
    assert entry.review_stage == ReviewStage.awaiting_review
    assert "09:00" in entry.slot_local


def test_uploaded_list_live_vs_scheduled(tmp_path):
    reader = FakeReader(
        clips=[
            FakeClip(
                clip_id="live1",
                youtube_video_id="aaa",
                publish_at_utc="2026-05-30T01:00:00Z",
                suggested_title="Live clip",
            ),
            FakeClip(
                clip_id="sched1",
                youtube_video_id="bbb",
                publish_at_utc="2026-06-10T01:00:00Z",
                suggested_title="Future clip",
            ),
        ]
    )
    scan = ScanResult(by_clip_id={}, by_slug={})

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    by_id = {u.clip_id: u for u in view.uploaded}
    assert by_id["live1"].is_live is True
    assert by_id["sched1"].is_live is False
    assert "aaa" in by_id["live1"].youtube_url


def test_header_counts_and_spend(tmp_path):
    clip_id = "clipG"
    slug = title_slug("Spend", clip_id)
    reader = FakeReader(
        clips=[FakeClip(clip_id=clip_id, title_slug=slug, script_id=clip_id)],
        unscripted_count=28,
        spend_today=120,
        spend_week=340,
        script_totals={clip_id: 180},
    )
    scan = _scan(tmp_path, pending=f"__unscheduled__{clip_id}__{slug}.mp4")

    view = build_dashboard_view(reader, scan, now=NOW, tz=SGT, ai_gen=_caps())

    assert view.header.stage_counts[ReviewStage.awaiting_review] == 1
    assert view.header.spend_today_cents == 120
    assert view.header.spend_week_cents == 340
    assert view.header.unscripted_topics == 28
    assert view.header.per_clip_cap_cents == 250
    assert view.header.daily_cap_cents == 500
