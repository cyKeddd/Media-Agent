"""M1 — dashboard health rollup (Pipeline health)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.dashboard.run_reader import RunSnapshot
from src.dashboard.scanner import ScanResult
from src.dashboard.view_model import (
    AlertView,
    PipelineStatus,
    build_dashboard_view,
)

SGT = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=SGT)


@dataclass
class FakeReader:
    clips: list = field(default_factory=list)
    unscripted_count: int = 0
    spend_today: int = 0
    spend_week: int = 0
    generation_run: RunSnapshot | None = None
    daily_run: RunSnapshot | None = None
    alerts: list = field(default_factory=list)

    def list_dashboard_clips(self):
        return self.clips

    def count_topics_by_status(self, status: str) -> int:
        if status == "unscripted":
            return self.unscripted_count
        return 0

    def quota_today_total(self, *, provider: str | None = None) -> int:
        return self.spend_today

    def quota_week_total(self, *, provider: str | None = None) -> int:
        return self.spend_week

    def quota_script_total(self, script_id: str) -> int:
        return 0

    def latest_runs(self) -> dict[str, RunSnapshot]:
        gen = self.generation_run or RunSnapshot(kind="generation", present=False)
        daily = self.daily_run or RunSnapshot(kind="daily", present=False)
        return {"generation": gen, "daily": daily}


def _caps():
    return SimpleNamespace(per_clip_cost_cents_max=250, daily_spend_cents_ceiling=500)


def _empty_scan(tmp_path: Path) -> ScanResult:
    for sub in ("pending", "approved", "rejected", "dry_run"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return ScanResult(by_clip_id={}, by_slug={})


def test_overall_status_healthy_when_runs_ok(tmp_path):
    reader = FakeReader(
        generation_run=RunSnapshot(
            kind="generation", present=True, started_at="2026-05-31 08:00:00",
            finished_at="2026-05-31 08:30:00", success=True, summary={"stages": {}},
        ),
        daily_run=RunSnapshot(
            kind="daily", present=True, started_at="2026-05-31 09:00:00",
            finished_at="2026-05-31 09:01:00", success=True, summary={"uploaded": 1},
        ),
    )
    view = build_dashboard_view(reader, _empty_scan(tmp_path), now=NOW, tz=SGT, ai_gen=_caps())
    assert view.health.overall_status == PipelineStatus.healthy


def test_overall_status_failed_when_generation_run_failed(tmp_path):
    reader = FakeReader(
        generation_run=RunSnapshot(
            kind="generation", present=True, started_at="2026-05-31 08:00:00",
            finished_at="2026-05-31 08:30:00", success=False,
            summary={"error": "boom"}, error="boom",
        ),
    )
    view = build_dashboard_view(reader, _empty_scan(tmp_path), now=NOW, tz=SGT, ai_gen=_caps())
    assert view.health.overall_status == PipelineStatus.failed


def test_overall_status_degraded_on_warning_alerts_only(tmp_path):
    reader = FakeReader(
        generation_run=RunSnapshot(
            kind="generation", present=True, started_at="2026-05-31 08:00:00",
            finished_at="2026-05-31 08:30:00", success=True, summary={"stages": {}},
        ),
    )
    alerts = [
        AlertView(
            timestamp="2026-05-31 06:16:42",
            kind="loudness_warn",
            message="warn",
            severity="warning",
        ),
    ]
    view = build_dashboard_view(
        reader, _empty_scan(tmp_path), now=NOW, tz=SGT, ai_gen=_caps(), recent_alerts=alerts,
    )
    assert view.health.overall_status == PipelineStatus.degraded
