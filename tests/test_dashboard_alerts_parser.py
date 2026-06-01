"""M3 — dashboard alerts parser."""

from __future__ import annotations

import pytest

from src.dashboard.alerts_parser import alert_severity, parse_alerts_tail


SAMPLE = """# Alerts

| timestamp_utc | kind | message |
| --- | --- | --- |
| 2026-05-12 10:59:16 | loudness_warn | loudness off target |
| 2026-05-26 15:26:29 | gen_run_failed | ModuleNotFoundError: feedparser |

[2026-05-21T11:33:13Z] kind=spike_kling_complete verdict=USEFUL

not a valid line

| broken | row |
| 2026-05-31 06:16:42 | gen_run_finished | gen_run finished |
"""


def test_parse_alerts_newest_first_with_tail_limit(tmp_path):
    path = tmp_path / "alerts.md"
    path.write_text(SAMPLE, encoding="utf-8")
    entries = parse_alerts_tail(path, limit=3)
    assert len(entries) == 3
    assert entries[0].kind == "gen_run_finished"
    assert entries[-1].kind == "gen_run_failed"
    assert all(e.severity for e in entries)


def test_severity_mapping():
    assert alert_severity("gen_run_failed") == "error"
    assert alert_severity("loudness_warn") == "warning"
    assert alert_severity("gen_run_finished") == "info"
    assert alert_severity("unknown_kind_xyz") == "info"


def test_malformed_lines_skipped(tmp_path):
    path = tmp_path / "alerts.md"
    path.write_text("garbage\n\n| bad |\n", encoding="utf-8")
    assert parse_alerts_tail(path) == []
