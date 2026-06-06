"""Compute next scheduled generation and daily Run fire times."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GENERATION_WEEKDAY = 6  # Sunday
GENERATION_HOUR = 2
GENERATION_MINUTE = 0
DAILY_HOUR = 9
DAILY_MINUTE = 0


def _next_weekly_generation(now_local: datetime) -> datetime:
    """Next Sunday 02:00 in the caller's local tz."""
    days_ahead = (GENERATION_WEEKDAY - now_local.weekday()) % 7
    candidate = now_local.replace(
        hour=GENERATION_HOUR,
        minute=GENERATION_MINUTE,
        second=0,
        microsecond=0,
    ) + timedelta(days=days_ahead)
    if candidate <= now_local:
        candidate += timedelta(days=7)
    return candidate


def _next_daily_upload(now_local: datetime) -> datetime:
    """Next 09:00 in the caller's local tz."""
    candidate = now_local.replace(
        hour=DAILY_HOUR,
        minute=DAILY_MINUTE,
        second=0,
        microsecond=0,
    )
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate


def compute_next_runs(
    now: datetime,
    tz: ZoneInfo,
) -> dict[str, datetime]:
    """Return tz-aware next-fire datetimes per Run kind."""
    now_local = now.astimezone(tz)
    return {
        "generation": _next_weekly_generation(now_local),
        "daily": _next_daily_upload(now_local),
    }
