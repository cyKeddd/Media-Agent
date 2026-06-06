"""Operator overrides — reschedule slot and edit title (ADR-0007)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.editor.slug import title_slug
from src.uploader.publish_at import format_publish_at_iso_z, pad_publish_at

_SLOT_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}__slot_\d{4}__")


@dataclass(frozen=True)
class MutationPlan:
    clip_id: str
    db_updates: dict[str, Any]
    from_path: Path
    to_path: Path
    warning: str | None = None


@dataclass(frozen=True)
class MutationRefusal:
    message: str
    code: str


@dataclass(frozen=True)
class MutationResult:
    ok: bool
    refused: bool
    message: str
    clip_id: str
    action: str
    warning: str | None = None


def _row_val(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, default)


def _published(clip_row: Any) -> bool:
    return bool(_row_val(clip_row, "youtube_video_id"))


def _rename_with_new_slug(from_path: Path, clip_id: str, slug: str) -> Path:
    basename = from_path.name
    m = re.match(r"^(\d{4}-\d{2}-\d{2}__slot_\d{4}__)", basename)
    if m:
        return from_path.parent / f"{m.group(1)}{slug}.mp4"
    m = re.match(r"^(__unscheduled__.+?__)", basename)
    if m:
        return from_path.parent / f"{m.group(1)}{slug}.mp4"
    return from_path.parent / f"{slug}.mp4"


def _basename_slug(output_path: str | None, clip_id: str, suggested_title: str) -> str:
    if output_path:
        basename = Path(output_path).name
        m = _SLOT_PREFIX_RE.match(basename)
        if m:
            return basename[m.end() :].rsplit(".", 1)[0]
        if basename.endswith(".mp4"):
            return basename[:-4]
    return title_slug(suggested_title or "", clip_id)


def snap_to_half_hour(dt: datetime) -> datetime:
    """Snap a tz-aware datetime to :00 or :30."""
    minute = dt.minute
    if minute < 15:
        snapped = 0
        extra_hours = 0
    elif minute < 45:
        snapped = 30
        extra_hours = 0
    else:
        snapped = 0
        extra_hours = 1
    return (dt + timedelta(hours=extra_hours)).replace(
        minute=snapped, second=0, microsecond=0,
    )


def plan_reschedule(
    clip_row: Any,
    new_dt: datetime,
    tz: ZoneInfo,
    now: datetime,
    *,
    collision_clip_ids: list[str] | None = None,
) -> MutationPlan | MutationRefusal:
    if _published(clip_row):
        return MutationRefusal("clip is already published", "published")
    if new_dt.tzinfo is None:
        return MutationRefusal("datetime must be timezone-aware", "invalid_datetime")
    local_dt = snap_to_half_hour(new_dt.astimezone(tz))
    utc_dt = local_dt.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    _, was_padded = pad_publish_at(utc_dt, now_utc)
    if was_padded:
        return MutationRefusal(
            "slot must be at least 20 minutes in the future",
            "too_soon",
        )
    output_path = _row_val(clip_row, "output_path")
    if not output_path:
        return MutationRefusal("clip has no output_path", "no_output_path")
    from_path = Path(output_path)
    slug = _basename_slug(
        output_path,
        _row_val(clip_row, "clip_id"),
        _row_val(clip_row, "suggested_title", ""),
    )
    filename_date = local_dt.strftime("%Y-%m-%d")
    filename_hhmm = local_dt.strftime("%H%M")
    new_name = f"{filename_date}__slot_{filename_hhmm}__{slug}.mp4"
    to_path = from_path.parent / new_name
    publish_at_utc = format_publish_at_iso_z(utc_dt)
    publish_slot_local = local_dt.strftime("%Y-%m-%d %H:%M")
    warning = None
    if collision_clip_ids:
        warning = (
            f"slot collision with {len(collision_clip_ids)} other clip(s): "
            f"{', '.join(collision_clip_ids[:3])}"
        )
    return MutationPlan(
        clip_id=_row_val(clip_row, "clip_id"),
        db_updates={
            "publish_at_utc": publish_at_utc,
            "publish_slot_local": publish_slot_local,
            "output_path": str(to_path),
        },
        from_path=from_path,
        to_path=to_path,
        warning=warning,
    )


def plan_edit_title(
    clip_row: Any,
    new_title: str,
    clip_id: str,
) -> MutationPlan | MutationRefusal:
    if _published(clip_row):
        return MutationRefusal("clip is already published", "published")
    text = (new_title or "").strip()
    if not text:
        return MutationRefusal("title must not be empty", "empty_title")
    output_path = _row_val(clip_row, "output_path")
    if not output_path:
        return MutationRefusal("clip has no output_path", "no_output_path")
    from_path = Path(output_path)
    slug = title_slug(text, clip_id)
    to_path = _rename_with_new_slug(from_path, clip_id, slug)
    return MutationPlan(
        clip_id=clip_id,
        db_updates={
            "suggested_title": text,
            "hook": text,
            "title_slug": slug,
            "output_path": str(to_path),
        },
        from_path=from_path,
        to_path=to_path,
    )


def apply_mutation_plan(repo, plan: MutationPlan) -> None:
    """DB-first then rename on disk."""
    with repo.tx():
        repo.set_clip_status(plan.clip_id, clip_row_status(repo, plan.clip_id), **plan.db_updates)
    plan.to_path.parent.mkdir(parents=True, exist_ok=True)
    if plan.from_path.exists():
        os.replace(plan.from_path, plan.to_path)


def clip_row_status(repo, clip_id: str) -> str:
    row = repo.get_clip(clip_id)
    return row["status"] if row else "quality_pass"
