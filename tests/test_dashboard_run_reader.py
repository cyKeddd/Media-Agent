"""M2 — dashboard run reader (latest Run per kind)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.dashboard.run_reader import latest_run_per_kind
from src.state import initialize_schema


def _db(tmp_path):
    conn = sqlite3.connect(tmp_path / "runs.db")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    return conn


def _insert_run(conn, *, kind: str, started_at: str, finished_at: str | None, success: int | None, summary: str | None):
    conn.execute(
        "INSERT INTO runs (kind, started_at, finished_at, success, summary_json) VALUES (?, ?, ?, ?, ?)",
        (kind, started_at, finished_at, success, summary),
    )
    conn.commit()


def test_latest_run_per_kind_empty_table(tmp_path):
    conn = _db(tmp_path)
    result = latest_run_per_kind(conn, kinds=("generation", "daily"))
    assert result["generation"].present is False
    assert result["daily"].present is False


def test_latest_run_per_kind_picks_newest(tmp_path):
    conn = _db(tmp_path)
    _insert_run(
        conn,
        kind="generation",
        started_at="2026-05-30 10:00:00",
        finished_at="2026-05-30 10:05:00",
        success=1,
        summary='{"stages": {"topic_ingest": {"count": 3}}}',
    )
    _insert_run(
        conn,
        kind="generation",
        started_at="2026-05-31 10:00:00",
        finished_at="2026-05-31 10:10:00",
        success=0,
        summary='{"error": "ModuleNotFoundError: feedparser"}',
    )
    result = latest_run_per_kind(conn, kinds=("generation",))
    run = result["generation"]
    assert run.present is True
    assert run.started_at == "2026-05-31 10:00:00"
    assert run.success is False
    assert run.error == "ModuleNotFoundError: feedparser"


def test_daily_and_generation_independent(tmp_path):
    conn = _db(tmp_path)
    _insert_run(
        conn,
        kind="generation",
        started_at="2026-05-31 08:00:00",
        finished_at="2026-05-31 08:30:00",
        success=1,
        summary='{"stages": {}}',
    )
    _insert_run(
        conn,
        kind="daily",
        started_at="2026-05-31 09:00:00",
        finished_at="2026-05-31 09:01:00",
        success=1,
        summary='{"uploaded": 2}',
    )
    result = latest_run_per_kind(conn)
    assert result["generation"].present is True
    assert result["daily"].present is True
    assert result["daily"].success is True
