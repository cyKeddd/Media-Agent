"""Pure view-model for the read-only dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from src.dashboard.run_reader import RunSnapshot
from src.dashboard.scanner import ScanResult
from src.editor.slug import title_slug


class PipelineStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    failed = "failed"


class ReviewStage(str, Enum):
    awaiting_review = "awaiting_review"
    approved_scheduled = "approved_scheduled"
    published = "published"
    rejected = "rejected"
    unknown = "unknown"


class DashboardReader(Protocol):
    def list_dashboard_clips(self) -> list[Any]: ...
    def count_topics_by_status(self, status: str) -> int: ...
    def quota_today_total(self, *, provider: str | None = None) -> int: ...
    def quota_week_total(self, *, provider: str | None = None) -> int: ...
    def quota_script_total(self, script_id: str) -> int: ...
    def latest_runs(self) -> dict[str, RunSnapshot]: ...


@dataclass(frozen=True)
class ClipView:
    clip_id: str
    title: str
    hook: str
    content_kind: str
    review_stage: ReviewStage
    publish_at_utc: str | None
    publish_at_local: str | None
    file_subdir: str | None
    video_relpath: str | None
    per_clip_cost_cents: int | None
    shot_mix: str | None


@dataclass(frozen=True)
class ReviewQueueItem:
    clip_id: str
    title: str
    hook: str
    content_kind: str
    publish_at_local: str | None
    video_relpath: str | None
    shot_mix: str | None


@dataclass(frozen=True)
class CalendarEntry:
    clip_id: str
    title: str
    review_stage: ReviewStage
    slot_local: str
    publish_at_utc: str
    video_relpath: str | None


@dataclass(frozen=True)
class UploadedItem:
    clip_id: str
    title: str
    youtube_video_id: str
    youtube_url: str
    is_live: bool
    publish_at_local: str | None


@dataclass(frozen=True)
class HeaderView:
    stage_counts: dict[ReviewStage, int]
    spend_today_cents: int
    spend_week_cents: int
    per_clip_cap_cents: int
    daily_cap_cents: int
    unscripted_topics: int


@dataclass(frozen=True)
class RunTileView:
    kind: str
    present: bool
    started_at: str | None
    finished_at: str | None
    success: bool | None
    label: str
    detail: str | None
    error: str | None


@dataclass(frozen=True)
class AlertView:
    timestamp: str
    kind: str
    message: str
    severity: str


@dataclass(frozen=True)
class HealthView:
    overall_status: PipelineStatus
    generation_run: RunTileView
    daily_run: RunTileView
    spend_today_cents: int
    spend_week_cents: int
    per_clip_cap_cents: int
    daily_cap_cents: int
    unscripted_topics: int
    alerts: list[AlertView]


@dataclass(frozen=True)
class DashboardView:
    clips: list[ClipView]
    review_queue: list[ReviewQueueItem]
    calendar_by_date: dict[str, list[CalendarEntry]]
    uploaded: list[UploadedItem]
    header: HeaderView
    health: HealthView
    human_review: bool = True


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, default)


def _resolve_location(
    clip_id: str,
    title_slug_val: str | None,
    suggested_title: str,
    scan: ScanResult,
) -> tuple[str | None, Path | None]:
    if clip_id in scan.by_clip_id:
        subdir, path = scan.by_clip_id[clip_id]
        return subdir, path
    slug = title_slug_val or title_slug(suggested_title or "", clip_id)
    if slug in scan.by_slug:
        subdir, path = scan.by_slug[slug]
        return subdir, path
    return None, None


def _shot_mix(shots_json: str | None) -> str | None:
    if not shots_json:
        return None
    try:
        shots = json.loads(shots_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(shots, list):
        return None
    kinds = [s.get("kind") or s.get("shot_kind") for s in shots if isinstance(s, dict)]
    if not kinds:
        return None
    real = sum(1 for k in kinds if k == "real_image")
    ai = sum(1 for k in kinds if k == "ai_video")
    if real or ai:
        return f"{real} real / {ai} AI"
    return None


def _derive_stage(
    *,
    status: str,
    youtube_video_id: str | None,
    publish_at_utc: str | None,
    file_subdir: str | None,
) -> ReviewStage:
    if youtube_video_id:
        return ReviewStage.published
    if status.startswith("rejected_") or file_subdir == "rejected":
        return ReviewStage.rejected
    if file_subdir == "approved" and publish_at_utc:
        return ReviewStage.approved_scheduled
    if file_subdir == "pending":
        return ReviewStage.awaiting_review
    return ReviewStage.unknown


def _to_local(iso_utc: str, tz: ZoneInfo) -> str:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _local_date(iso_utc: str, tz: ZoneInfo) -> str:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(tz).strftime("%Y-%m-%d")


def _local_time(iso_utc: str, tz: ZoneInfo) -> str:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(tz).strftime("%H:%M")


def _run_tile(snapshot: RunSnapshot) -> RunTileView:
    if not snapshot.present:
        return RunTileView(
            kind=snapshot.kind,
            present=False,
            started_at=None,
            finished_at=None,
            success=None,
            label="Not yet run",
            detail=None,
            error=None,
        )
    if snapshot.finished and snapshot.success is False:
        label = "Failed"
        detail = snapshot.error
    elif not snapshot.finished:
        label = "In progress"
        detail = None
    else:
        label = "OK"
        detail = _run_success_detail(snapshot)
    return RunTileView(
        kind=snapshot.kind,
        present=True,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        success=snapshot.success,
        label=label,
        detail=detail,
        error=snapshot.error if snapshot.failed else None,
    )


def _run_success_detail(snapshot: RunSnapshot) -> str | None:
    summary = snapshot.summary or {}
    if snapshot.kind == "daily":
        if "uploaded" in summary:
            return f"uploaded={summary['uploaded']}"
        if summary.get("message") == "no_candidates":
            return "no_candidates"
        return None
    stages = summary.get("stages")
    if isinstance(stages, dict) and stages:
        parts = []
        for name, val in stages.items():
            if isinstance(val, dict) and "count" in val:
                parts.append(f"{name}={val['count']}")
            else:
                parts.append(name)
        return ", ".join(parts[:6]) if parts else None
    return None


def derive_overall_status(
    *,
    generation: RunSnapshot,
    daily: RunSnapshot,
    alerts: list[AlertView],
) -> PipelineStatus:
    if generation.failed or daily.failed:
        return PipelineStatus.failed
    if any(a.severity == "warning" for a in alerts):
        return PipelineStatus.degraded
    if any(a.severity == "error" for a in alerts):
        return PipelineStatus.failed
    return PipelineStatus.healthy


def build_dashboard_view(
    reader: DashboardReader,
    scan: ScanResult,
    *,
    now: datetime,
    tz: ZoneInfo,
    ai_gen: Any,
    output_root: Path | None = None,
    recent_alerts: list[AlertView] | None = None,
    human_review: bool = True,
) -> DashboardView:
    """Assemble the four dashboard sections from injected read dependencies."""
    clip_views: list[ClipView] = []
    review_queue: list[ReviewQueueItem] = []
    calendar_by_date: dict[str, list[CalendarEntry]] = {}
    uploaded: list[UploadedItem] = []
    stage_counts: dict[ReviewStage, int] = {s: 0 for s in ReviewStage}

    for row in reader.list_dashboard_clips():
        clip_id = _row_get(row, "clip_id", "")
        suggested_title = _row_get(row, "suggested_title") or _row_get(row, "script_title") or ""
        title = _row_get(row, "script_title") or suggested_title
        hook = _row_get(row, "hook") or ""
        if not hook and _row_get(row, "script_narration"):
            words = str(_row_get(row, "script_narration")).split()
            hook = " ".join(words[:5])
        content_kind = _row_get(row, "content_kind") or "sourced"
        status = _row_get(row, "status") or ""
        publish_at_utc = _row_get(row, "publish_at_utc")
        youtube_video_id = _row_get(row, "youtube_video_id")
        script_id = _row_get(row, "script_id")
        title_slug_val = _row_get(row, "title_slug")
        shots_json = _row_get(row, "shots_json") or _row_get(row, "s_shots_json")

        file_subdir, file_path = _resolve_location(
            clip_id, title_slug_val, suggested_title, scan,
        )
        video_relpath = None
        if file_path and output_root:
            try:
                video_relpath = file_path.relative_to(output_root).as_posix()
            except ValueError:
                video_relpath = None
        elif file_path:
            video_relpath = file_path.name

        stage = _derive_stage(
            status=status,
            youtube_video_id=youtube_video_id,
            publish_at_utc=publish_at_utc,
            file_subdir=file_subdir,
        )
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

        per_clip_cost = None
        if script_id:
            total = reader.quota_script_total(script_id)
            if total > 0:
                per_clip_cost = total

        mix = _shot_mix(shots_json)
        publish_local = _to_local(publish_at_utc, tz) if publish_at_utc else None

        cv = ClipView(
            clip_id=clip_id,
            title=title,
            hook=hook,
            content_kind=content_kind,
            review_stage=stage,
            publish_at_utc=publish_at_utc,
            publish_at_local=publish_local,
            file_subdir=file_subdir,
            video_relpath=video_relpath,
            per_clip_cost_cents=per_clip_cost,
            shot_mix=mix,
        )
        clip_views.append(cv)

        if stage == ReviewStage.awaiting_review:
            review_queue.append(
                ReviewQueueItem(
                    clip_id=clip_id,
                    title=title,
                    hook=hook,
                    content_kind=content_kind,
                    publish_at_local=publish_local,
                    video_relpath=video_relpath,
                    shot_mix=mix,
                )
            )

        if publish_at_utc:
            date_key = _local_date(publish_at_utc, tz)
            calendar_by_date.setdefault(date_key, []).append(
                CalendarEntry(
                    clip_id=clip_id,
                    title=title,
                    review_stage=stage,
                    slot_local=_local_time(publish_at_utc, tz),
                    publish_at_utc=publish_at_utc,
                    video_relpath=video_relpath,
                )
            )

        if youtube_video_id:
            is_live = False
            if publish_at_utc:
                pub_dt = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00"))
                is_live = pub_dt <= now.astimezone(pub_dt.tzinfo)
            uploaded.append(
                UploadedItem(
                    clip_id=clip_id,
                    title=title,
                    youtube_video_id=youtube_video_id,
                    youtube_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
                    is_live=is_live,
                    publish_at_local=publish_local,
                )
            )

    spend_today = reader.quota_today_total(provider="openrouter")
    spend_week = reader.quota_week_total(provider="openrouter")
    per_clip_cap = int(ai_gen.per_clip_cost_cents_max)
    daily_cap = int(ai_gen.daily_spend_cents_ceiling)
    unscripted = reader.count_topics_by_status("unscripted")

    header = HeaderView(
        stage_counts=stage_counts,
        spend_today_cents=spend_today,
        spend_week_cents=spend_week,
        per_clip_cap_cents=per_clip_cap,
        daily_cap_cents=daily_cap,
        unscripted_topics=unscripted,
    )

    runs = reader.latest_runs()
    gen_snap = runs.get("generation") or RunSnapshot(kind="generation", present=False)
    daily_snap = runs.get("daily") or RunSnapshot(kind="daily", present=False)
    alert_views = list(recent_alerts or [])
    health = HealthView(
        overall_status=derive_overall_status(
            generation=gen_snap,
            daily=daily_snap,
            alerts=alert_views,
        ),
        generation_run=_run_tile(gen_snap),
        daily_run=_run_tile(daily_snap),
        spend_today_cents=spend_today,
        spend_week_cents=spend_week,
        per_clip_cap_cents=per_clip_cap,
        daily_cap_cents=daily_cap,
        unscripted_topics=unscripted,
        alerts=alert_views,
    )

    return DashboardView(
        clips=clip_views,
        review_queue=review_queue,
        calendar_by_date=calendar_by_date,
        uploaded=uploaded,
        header=header,
        health=health,
        human_review=human_review,
    )


def view_to_json(view: DashboardView) -> dict:
    """Serialize DashboardView for the /api/view endpoint."""

    def _stage(s: ReviewStage) -> str:
        return s.value

    def _run_tile_json(t: RunTileView) -> dict:
        return {
            "kind": t.kind,
            "present": t.present,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
            "success": t.success,
            "label": t.label,
            "detail": t.detail,
            "error": t.error,
        }

    return {
        "human_review": view.human_review,
        "health": {
            "overall_status": view.health.overall_status.value,
            "generation_run": _run_tile_json(view.health.generation_run),
            "daily_run": _run_tile_json(view.health.daily_run),
            "spend_today_cents": view.health.spend_today_cents,
            "spend_week_cents": view.health.spend_week_cents,
            "per_clip_cap_cents": view.health.per_clip_cap_cents,
            "daily_cap_cents": view.health.daily_cap_cents,
            "unscripted_topics": view.health.unscripted_topics,
            "alerts": [
                {
                    "timestamp": a.timestamp,
                    "kind": a.kind,
                    "message": a.message,
                    "severity": a.severity,
                }
                for a in view.health.alerts
            ],
        },
        "review_queue": [
            {
                "clip_id": i.clip_id,
                "title": i.title,
                "hook": i.hook,
                "content_kind": i.content_kind,
                "publish_at_local": i.publish_at_local,
                "video_relpath": i.video_relpath,
                "shot_mix": i.shot_mix,
            }
            for i in view.review_queue
        ],
        "calendar_by_date": {
            d: [
                {
                    "clip_id": e.clip_id,
                    "title": e.title,
                    "review_stage": _stage(e.review_stage),
                    "slot_local": e.slot_local,
                    "publish_at_utc": e.publish_at_utc,
                    "video_relpath": e.video_relpath,
                }
                for e in entries
            ]
            for d, entries in sorted(view.calendar_by_date.items())
        },
        "uploaded": [
            {
                "clip_id": u.clip_id,
                "title": u.title,
                "youtube_video_id": u.youtube_video_id,
                "youtube_url": u.youtube_url,
                "is_live": u.is_live,
                "publish_at_local": u.publish_at_local,
            }
            for u in view.uploaded
        ],
        "header": {
            "stage_counts": {k.value: v for k, v in view.header.stage_counts.items()},
            "spend_today_cents": view.header.spend_today_cents,
            "spend_week_cents": view.header.spend_week_cents,
            "per_clip_cap_cents": view.header.per_clip_cap_cents,
            "daily_cap_cents": view.header.daily_cap_cents,
            "unscripted_topics": view.header.unscripted_topics,
        },
        "clips": [
            {
                "clip_id": c.clip_id,
                "title": c.title,
                "review_stage": _stage(c.review_stage),
                "video_relpath": c.video_relpath,
            }
            for c in view.clips
        ],
    }
