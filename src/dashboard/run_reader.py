"""Read latest Run rows per kind from the runs table (SELECT-only)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

_DEFAULT_KINDS = ("generation", "daily")


@dataclass(frozen=True)
class RunSnapshot:
    kind: str
    present: bool
    run_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    success: bool | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None

    @property
    def finished(self) -> bool:
        return self.present and self.finished_at is not None

    @property
    def failed(self) -> bool:
        return self.finished and self.success is False


def _parse_summary(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    err = data.get("error")
    if err is not None:
        return data, str(err)
    return data, None


def _row_to_snapshot(kind: str, row: sqlite3.Row | None) -> RunSnapshot:
    if row is None:
        return RunSnapshot(kind=kind, present=False)
    summary, error = _parse_summary(row["summary_json"])
    success_val = row["success"]
    success = None if success_val is None else bool(success_val)
    return RunSnapshot(
        kind=kind,
        present=True,
        run_id=row["run_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        success=success,
        summary=summary,
        error=error,
    )


def latest_run_per_kind(
    conn: sqlite3.Connection,
    *,
    kinds: tuple[str, ...] = _DEFAULT_KINDS,
) -> dict[str, RunSnapshot]:
    """Return the most recent finished-or-in-progress Run per kind."""
    result: dict[str, RunSnapshot] = {}
    for kind in kinds:
        row = conn.execute(
            """
            SELECT run_id, kind, started_at, finished_at, success, summary_json
            FROM runs
            WHERE kind = ?
            ORDER BY run_id DESC
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        result[kind] = _row_to_snapshot(kind, row)
    return result
