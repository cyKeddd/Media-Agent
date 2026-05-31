"""Issue 39 — backfill-gate legacy unscripted topics (injected classifier only)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.state import Repository, connect, initialize_schema
from src.topic_ingest.niche_gate import NicheVerdict


def _cfg():
    return SimpleNamespace(ollama_model="qwen2.5:3b-instruct")


def _repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _insert_unscripted(repo: Repository, title: str, summary: str | None = None) -> int:
    return repo.insert_topic(
        url=f"https://example.com/{title.replace(' ', '-')}",
        title=title,
        summary=summary,
        source_feed="https://feed.test/rss",
        fetched_at="2026-05-20T00:00:00Z",
    )


def test_off_niche_topic_rejected(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    tid = _insert_unscripted(repo, "AI startup raises $20M Series B", "funding round")

    def _classify(title, summary, *, model):
        return NicheVerdict(
            verdict="off_niche",
            reason="startup funding",
            infrastructure_failed=False,
        )

    result = backfill_unscripted_topics(_cfg(), repo, _classify=_classify)

    assert result.rejected == 1
    assert result.kept == 0
    assert result.infra_skipped == 0
    row = repo.conn.execute("SELECT status FROM topics WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "rejected_off_niche"


def test_on_niche_topic_kept(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    tid = _insert_unscripted(repo, "GPT-5.5 released by OpenAI", "frontier model launch")

    def _classify(title, summary, *, model):
        return NicheVerdict(
            verdict="on_niche",
            reason="major AI model launch",
            infrastructure_failed=False,
        )

    result = backfill_unscripted_topics(_cfg(), repo, _classify=_classify)

    assert result.kept == 1
    assert result.rejected == 0
    assert result.infra_skipped == 0
    row = repo.conn.execute("SELECT status FROM topics WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "unscripted"


def test_infra_failure_kept_and_counted(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    tid = _insert_unscripted(repo, "Gemini 2.5 Pro update", "Google AI release")

    def _classify(title, summary, *, model):
        return NicheVerdict(
            verdict="off_niche",
            reason="ollama unreachable",
            infrastructure_failed=True,
        )

    result = backfill_unscripted_topics(_cfg(), repo, _classify=_classify)

    assert result.infra_skipped == 1
    assert result.kept == 1
    assert result.rejected == 0
    row = repo.conn.execute("SELECT status FROM topics WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "unscripted"


def test_dry_run_writes_nothing(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    _insert_unscripted(repo, "OnlyFans TV show on Apple TV", "culture story")

    def _classify(title, summary, *, model):
        return NicheVerdict(
            verdict="off_niche",
            reason="culture entertainment",
            infrastructure_failed=False,
        )

    result = backfill_unscripted_topics(_cfg(), repo, _classify=_classify, dry_run=True)

    assert result.rejected == 1
    rows = repo.conn.execute("SELECT status FROM topics").fetchall()
    assert all(r["status"] == "unscripted" for r in rows)


def test_idempotent_skips_already_rejected(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    tid = _insert_unscripted(repo, "Culture drama lawsuit", "industry gossip")
    repo.mark_topic_rejected_off_niche(tid)

    calls = {"n": 0}

    def _classify(title, summary, *, model):
        calls["n"] += 1
        return NicheVerdict(
            verdict="off_niche",
            reason="should not run",
            infrastructure_failed=False,
        )

    result = backfill_unscripted_topics(_cfg(), repo, _classify=_classify)

    assert result.rejected == 0
    assert result.kept == 0
    assert calls["n"] == 0


def test_scripter_selection_excludes_rejected_off_niche(tmp_path):
    from src.topic_ingest.backfill import backfill_unscripted_topics

    repo = _repo(tmp_path)
    _insert_unscripted(repo, "Off niche IPO news", "business")
    _insert_unscripted(repo, "Claude Opus 4.7 released", "AI model")

    titles = {}

    def _classify(title, summary, *, model):
        if "IPO" in title:
            return NicheVerdict("off_niche", "business", False)
        return NicheVerdict("on_niche", "AI launch", False)

    backfill_unscripted_topics(_cfg(), repo, _classify=_classify)

    unscripted = repo.unscripted_topics()
    assert len(unscripted) == 1
    assert "Claude" in unscripted[0]["title"]
