"""Repository adapter + CLI entry for the read-only dashboard."""

from __future__ import annotations

from src.dashboard.app import create_app
from src.dashboard.run_reader import latest_run_per_kind
from src.dashboard.view_model import DashboardReader


class RepositoryDashboardReader:
    """Read-only facade over Repository for the dashboard view-model."""

    def __init__(self, repo) -> None:
        self._repo = repo

    def list_dashboard_clips(self):
        return self._repo.list_dashboard_clips()

    def count_topics_by_status(self, status: str) -> int:
        return self._repo.count_topics_by_status(status)

    def quota_today_total(self, *, provider: str | None = None) -> int:
        return self._repo.quota_today_total(provider=provider)

    def quota_week_total(self, *, provider: str | None = None) -> int:
        return self._repo.quota_week_total(provider=provider)

    def quota_script_total(self, script_id: str) -> int:
        return self._repo.quota_script_total(script_id)

    def latest_runs(self):
        return latest_run_per_kind(self._repo.conn)


def build_reader(repo) -> DashboardReader:
    return RepositoryDashboardReader(repo)
