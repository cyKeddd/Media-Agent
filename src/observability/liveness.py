"""Liveness alert — Issue 61 / INV-5.

If no `clips` row has been rendered within `cfg.liveness_stale_days` (new
config key, default 7), append a `liveness_stalled` alert on the next run
of either entry point (`gen_run.py` / `daily_upload.py`), naming the
elapsed days and the last rendered Clip.

Every clip row is inserted with status='rendered' at creation time
(see src.gen_run._persist_rendered_clip), so `clips.created_at` is the
render timestamp for every clip regardless of what status it has
progressed to since (quality_pass / approved / uploaded / ...). No
Repository method addition is needed — this queries `repo.conn` directly,
the same pattern `daily_upload.reconcile_approvals` already uses.

The alert fires at most once per calendar day (UTC): a long stall becomes
a daily heartbeat, not one alert per invocation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.observability.alerts import append_alert

LIVENESS_STALLED = "liveness_stalled"


def _parse_sqlite_timestamp(value: str) -> datetime:
    """Parse a clips.created_at value ('YYYY-MM-DD HH:MM:SS', SQLite's
    datetime('now') default format) or an ISO 'T'-separated timestamp into
    a tz-aware UTC datetime."""
    text = value.strip()
    if "T" in text:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _last_alert_date(logs_dir: Path, kind: str) -> str | None:
    """Return the UTC date ('YYYY-MM-DD') of the most recent alert of
    `kind` in logs/alerts.md, or None if the file/kind is absent."""
    alerts_path = Path(logs_dir) / "alerts.md"
    if not alerts_path.exists():
        return None
    last_date: str | None = None
    marker = f"| {kind} |"
    for line in alerts_path.read_text(encoding="utf-8").splitlines():
        if marker not in line:
            continue
        cols = line.split("|")
        if len(cols) < 2:
            continue
        ts = cols[1].strip()
        if ts:
            last_date = ts[:10]
    return last_date


def check_liveness(repo, cfg, logs_dir: str | Path, *, now: datetime | None = None) -> None:
    """INV-5: alert if no Clip has rendered within cfg.liveness_stale_days.

    Rendered-within-the-window -> no alert (early return). Stale ->
    append a `liveness_stalled` alert, but only once per UTC calendar day.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    stale_days = getattr(cfg, "liveness_stale_days", 7)

    row = repo.conn.execute(
        "SELECT clip_id, suggested_title, created_at FROM clips "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()

    if row is not None:
        rendered_at = _parse_sqlite_timestamp(row["created_at"])
        elapsed_days = (now - rendered_at).total_seconds() / 86400.0
        if elapsed_days <= stale_days:
            return  # rendered within the window -> no alert
        message = (
            f"{elapsed_days:.1f} days since the last rendered Clip "
            f"{row['clip_id']} ({row['suggested_title']!r}, rendered at "
            f"{row['created_at']}); stale threshold is {stale_days}d"
        )
    else:
        message = (
            f"no Clip has ever been rendered; stale threshold is {stale_days}d"
        )

    today = now.strftime("%Y-%m-%d")
    if _last_alert_date(logs_dir, LIVENESS_STALLED) == today:
        return  # already alerted today -> daily heartbeat, not per-invocation

    append_alert(logs_dir, kind=LIVENESS_STALLED, message=message, now=now)
