"""Issue 54 — next-run countdown computation and API shape."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.dashboard.next_run import compute_next_runs
from src.dashboard.view_model import build_dashboard_view

from tests.test_dashboard_view_model import FakeReader, _caps
from tests.test_dashboard_health import _empty_scan

SGT = ZoneInfo("Asia/Singapore")


def test_next_daily_before_nine_am_same_day():
    now = datetime(2026, 6, 6, 7, 30, tzinfo=SGT)
    runs = compute_next_runs(now, SGT)
    assert runs["daily"].day == 6
    assert runs["daily"].hour == 9
    assert runs["daily"].minute == 0


def test_next_daily_after_nine_am_tomorrow():
    now = datetime(2026, 6, 6, 10, 0, tzinfo=SGT)
    runs = compute_next_runs(now, SGT)
    assert runs["daily"].day == 7
    assert runs["daily"].hour == 9


def test_next_generation_on_sunday_before_two_am():
    # 2026-06-07 is Sunday
    now = datetime(2026, 6, 7, 1, 0, tzinfo=SGT)
    runs = compute_next_runs(now, SGT)
    assert runs["generation"].weekday() == 6
    assert runs["generation"].hour == 2


def test_next_generation_midweek_points_to_sunday():
    now = datetime(2026, 6, 4, 12, 0, tzinfo=SGT)  # Thursday
    runs = compute_next_runs(now, SGT)
    assert runs["generation"].weekday() == 6
    assert runs["generation"] > now


def test_view_model_includes_next_run(tmp_path):
    reader = FakeReader()
    view = build_dashboard_view(
        reader, _empty_scan(tmp_path), now=datetime(2026, 6, 6, 8, 0, tzinfo=SGT),
        tz=SGT, ai_gen=_caps(),
    )
    assert view.next_run.generation_at
    assert view.next_run.daily_at
