"""Parse structured Alerts from logs/alerts.md (pure over injected path)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_BRACKET_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+kind=(?P<kind>\S+)(?:\s+(?P<message>.*))?$"
)
_PIPE_RE = re.compile(
    r"^\|\s*(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(?P<kind>[^|]+)\s*\|\s*(?P<message>[^|]*)\s*\|\s*$"
)

_ERROR_KINDS = frozenset({
    "gen_run_failed",
    "orphan_reconcile_required",
    "upload_api_rejected",
})
_WARNING_KINDS = frozenset({
    "loudness_warn",
    "upload_quota_exceeded",
    "heatmap_low_hit_rate",
    "lock_held",
    "quality_no_transcript",
})
_INFO_KINDS = frozenset({
    "gen_run_finished",
    "recovered_slot",
    "publish_at_padded",
    "spike_kling_complete",
})


@dataclass(frozen=True)
class ParsedAlert:
    timestamp: str
    kind: str
    message: str
    severity: str


def alert_severity(kind: str) -> str:
    if kind in _ERROR_KINDS or kind.endswith("_failed"):
        return "error"
    if kind in _WARNING_KINDS or kind.endswith("_warn") or kind.endswith("_exceeded"):
        return "warning"
    if kind in _INFO_KINDS:
        return "info"
    return "info"


def _parse_line(line: str) -> ParsedAlert | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("---"):
        return None
    m = _BRACKET_RE.match(stripped)
    if m:
        kind = m.group("kind")
        message = (m.group("message") or "").strip() or kind
        return ParsedAlert(
            timestamp=m.group("ts"),
            kind=kind,
            message=message,
            severity=alert_severity(kind),
        )
    m = _PIPE_RE.match(stripped)
    if m:
        kind = m.group("kind").strip()
        message = m.group("message").strip()
        return ParsedAlert(
            timestamp=m.group("ts").strip(),
            kind=kind,
            message=message,
            severity=alert_severity(kind),
        )
    return None


def parse_alerts_tail(path: Path, *, limit: int = 20) -> list[ParsedAlert]:
    """Return the most recent alert entries, newest first."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed: list[ParsedAlert] = []
    for line in text.splitlines():
        entry = _parse_line(line)
        if entry is not None:
            parsed.append(entry)
    tail = parsed[-limit:] if limit else parsed
    return list(reversed(tail))
