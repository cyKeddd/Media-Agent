"""Issue 69 — Freshness: Techmeme, HN as topic source, Google News queries.

Verifies observable behaviour through the public interface:
  fetch_unscripted_topics(cfg, repo, *, _parse=None, _now=None,
                           _classify_niche=None, _fetch_hn=None) -> list[dict]

No live network calls. Fixture feed / HN payloads only.
"""

from __future__ import annotations

import time
import calendar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config_loader.loader import load_config
from src.state import Repository, connect, initialize_schema
from src.topic_ingest.hn import HnItem, fetch_hn_front_page, hn_corroboration
from src.topic_ingest.runner import HN_SOURCE_LABEL, fetch_unscripted_topics


_NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
_TECHMEME_URL = "https://www.techmeme.com/feed.xml"
_VENDOR_URL = "https://openai.com/blog/rss.xml"
_GNEWS_URL = "https://news.google.com/rss/search?q=%22AI+model%22+when:2d&hl=en-US&gl=US&ceid=US:en"


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


# ---------------------------------------------------------------------------
# cfg builder — mirrors tests/test_topic_ingest.py's _make_cfg, extended with
# an injectable hn block. Deliberately keeps hn absent-by-default so it stays
# compatible with the existing (untouched) test_topic_ingest.py fixtures.
# ---------------------------------------------------------------------------


def _make_cfg(
    tmp_path,
    *,
    feeds=None,
    recency_hours=48,
    jaccard_threshold=0.6,
    seen_topics_window_days=30,
    stopwords=None,
    niche_gate_enabled=False,
    low_yield_threshold=1,
    recency_hours_extended=96,
    hn_enabled=False,
    hn_topic_source_enabled=False,
):
    if stopwords is None:
        stopwords = [
            "the", "a", "an", "is", "are", "of", "in", "to", "and", "with",
            "its", "just", "new", "says", "said", "launches", "launch",
            "release", "releases", "debut", "debuts", "here", "now",
        ]
    niche_gate = SimpleNamespace(
        enabled=niche_gate_enabled,
        low_yield_threshold=low_yield_threshold,
        recency_hours_extended=recency_hours_extended,
    )
    hn = SimpleNamespace(
        enabled=hn_enabled,
        topic_source_enabled=hn_topic_source_enabled,
        top_stories_url="https://hn/top",
        item_url_template="https://hn/item/{id}",
        max_stories=30,
        corroboration_weight=2.0,
    )
    ti = SimpleNamespace(
        feeds=feeds if feeds is not None else [_VENDOR_URL],
        recency_hours=recency_hours,
        seen_topics_window_days=seen_topics_window_days,
        jaccard_threshold=jaccard_threshold,
        stopwords=stopwords,
        niche_gate=niche_gate if niche_gate_enabled else None,
        hn=hn,
    )
    return SimpleNamespace(
        topic_ingest=ti,
        ollama_model="qwen2.5:3b-instruct",
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _ts(dt: datetime) -> time.struct_time:
    return time.gmtime(calendar.timegm(dt.timetuple()))


def _entry(title, link, summary="", *, pub_dt=None, no_pub=False):
    e = SimpleNamespace(title=title, link=link, summary=summary)
    if not no_pub:
        e.published_parsed = _ts(pub_dt if pub_dt is not None else _NOW - timedelta(hours=1))
    return e


def _feed(entries):
    return SimpleNamespace(entries=entries, bozo=False)


def _make_parse(feed_map: dict):
    def _parse(url, **kwargs):
        val = feed_map.get(url, [])
        if isinstance(val, list):
            return _feed(val)
        return val
    return _parse


def _on_niche(title, summary, *, model):
    from src.topic_ingest.niche_gate import NicheVerdict
    return NicheVerdict("on_niche", "ai launch", False)


# ---------------------------------------------------------------------------
# Config: feeds + source_authority + regression on recency_hours
# ---------------------------------------------------------------------------


def test_config_declares_techmeme_hn_and_google_news_feeds():
    cfg = load_config(Path("config.yaml"))
    assert _TECHMEME_URL in cfg.topic_ingest.feeds

    gnews_feeds = [f for f in cfg.topic_ingest.feeds if f.startswith("https://news.google.com/rss/search")]
    assert 2 <= len(gnews_feeds) <= 3, "expected 2-3 narrow Google News keyword queries"
    # Narrow, AI-scoped queries — not one broad query.
    for feed in gnews_feeds:
        assert "q=" in feed and "AI" in feed

    assert cfg.topic_ingest.hn.enabled is True
    assert cfg.topic_ingest.hn.topic_source_enabled is True


def test_recency_hours_left_at_48_not_narrowed_in_this_issue():
    cfg = load_config(Path("config.yaml"))
    assert cfg.topic_ingest.recency_hours == 48


def test_source_authority_ranks_aggregators_below_vendor_blogs():
    cfg = load_config(Path("config.yaml"))
    mapping = cfg.scripter.source_authority

    vendor_values = [
        mapping[u] for u in (
            "https://openai.com/blog/rss.xml",
            "https://deepmind.google/blog/rss.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        )
    ]
    min_vendor = min(vendor_values)

    assert _TECHMEME_URL in mapping
    assert mapping[_TECHMEME_URL] < min_vendor

    assert HN_SOURCE_LABEL in mapping
    assert mapping[HN_SOURCE_LABEL] < min_vendor

    gnews_feeds = [f for f in cfg.topic_ingest.feeds if f.startswith("https://news.google.com/rss/search")]
    assert gnews_feeds, "fixture assumes google news feeds configured"
    for feed in gnews_feeds:
        assert feed in mapping
        assert mapping[feed] < min_vendor


# ---------------------------------------------------------------------------
# HN promoted to a topic source
# ---------------------------------------------------------------------------


def test_hn_front_page_items_passing_niche_gate_become_topics(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[], niche_gate_enabled=True, hn_enabled=True, hn_topic_source_enabled=True)
    fake_parse = _make_parse({})
    hn_items = [
        HnItem(title="Anthropic ships new Claude model", url="https://news.ycombinator.com/item?id=1"),
    ]

    result = fetch_unscripted_topics(
        cfg, repo,
        _parse=fake_parse,
        _now=lambda: _NOW,
        _classify_niche=_on_niche,
        _fetch_hn=lambda cfg_arg: hn_items,
    )

    assert len(result) == 1
    assert result[0]["title"] == "Anthropic ships new Claude model"
    assert result[0]["source_feed"] == HN_SOURCE_LABEL
    row = repo.conn.execute("SELECT * FROM topics").fetchone()
    assert row["source_feed"] == HN_SOURCE_LABEL


def test_hn_topic_source_disabled_when_config_flag_off(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[], niche_gate_enabled=True, hn_enabled=True, hn_topic_source_enabled=False)
    fake_parse = _make_parse({})
    hn_items = [HnItem(title="Anthropic ships new Claude model", url="https://news.ycombinator.com/item?id=1")]

    result = fetch_unscripted_topics(
        cfg, repo,
        _parse=fake_parse,
        _now=lambda: _NOW,
        _classify_niche=_on_niche,
        _fetch_hn=lambda cfg_arg: hn_items,
    )
    assert result == []


def test_hn_topic_source_absent_config_stays_backward_compatible(repo, tmp_path):
    """cfg.topic_ingest with no `hn` attribute at all (older / minimal test
    doubles, e.g. tests/test_topic_ingest.py's _make_cfg) must not error."""
    ti = SimpleNamespace(
        feeds=[_VENDOR_URL],
        recency_hours=48,
        seen_topics_window_days=30,
        jaccard_threshold=0.6,
        stopwords=["the", "a"],
        niche_gate=None,
        # no `hn` attribute at all
    )
    cfg = SimpleNamespace(
        topic_ingest=ti,
        ollama_model="qwen2.5:3b-instruct",
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )
    fake_parse = _make_parse({_VENDOR_URL: [_entry("GPT-5 Released", "https://example.com/gpt5")]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Regression guard — HN Trending-corroboration role unaffected
# ---------------------------------------------------------------------------


def test_hn_corroboration_role_still_works_after_promotion_to_topic_source():
    """The same fetched HN items must remain usable for Trending
    corroboration (scripter Stage A) exactly as before Issue 69 — promotion
    to a Topic source must not consume, mutate, or otherwise interfere with
    the existing corroboration pathway."""
    hn_items = [
        HnItem(title="Anthropic releases Claude Opus 4.7 model", url="https://example.com/a"),
        HnItem(title="Unrelated gaming console news", url="https://example.com/b"),
    ]
    topic_match = {"title": "Anthropic releases Claude Opus 4.7", "summary": None}
    topic_other = {"title": "Random widget patch notes", "summary": None}

    match_score = hn_corroboration(topic_match, hn_items, weight=2.0)
    other_score = hn_corroboration(topic_other, hn_items, weight=2.0)

    assert match_score > other_score
    assert match_score > 0

    # Same underlying client (fetch_hn_front_page) still importable/callable
    # with the classic corroboration-only config shape (no topic_source_enabled).
    cfg = SimpleNamespace(
        topic_ingest=SimpleNamespace(
            hn=SimpleNamespace(
                enabled=True,
                top_stories_url="https://hn/top",
                item_url_template="https://hn/item/{id}",
                max_stories=2,
            )
        )
    )

    def fake_get(url, timeout=None):
        import json
        if url.endswith("/top"):
            body = json.dumps([1])
        else:
            body = json.dumps({"title": "Story 1", "url": "https://ex/1"})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: json.loads(body))

    items = fetch_hn_front_page(cfg, _get=fake_get)
    assert len(items) == 1
    assert items[0].title == "Story 1"


def test_hn_client_reused_for_both_topic_sourcing_and_corroboration(repo, tmp_path):
    """One fetch of the HN front page can seed Topics AND drive corroboration
    scoring — this is the reuse the ticket requires (no second HN client)."""
    hn_items = [HnItem(title="Google ships new Gemini AI model", url="https://ex/1")]

    cfg = _make_cfg(tmp_path, feeds=[], niche_gate_enabled=True, hn_enabled=True, hn_topic_source_enabled=True)
    fetch_calls = []

    def _fetch_hn(cfg_arg):
        fetch_calls.append(cfg_arg)
        return hn_items

    result = fetch_unscripted_topics(
        cfg, repo,
        _parse=_make_parse({}),
        _now=lambda: _NOW,
        _classify_niche=_on_niche,
        _fetch_hn=_fetch_hn,
    )
    assert len(result) == 1
    assert len(fetch_calls) == 1

    # The exact same items list, reused for corroboration — no re-fetch needed.
    score = hn_corroboration({"title": "Gemini AI model launch", "summary": None}, hn_items)
    assert score > 0


# ---------------------------------------------------------------------------
# Dedup — the main risk: 4 sources, 4 URLs, 4 headlines -> 1 Topic
# ---------------------------------------------------------------------------


def test_same_story_from_four_sources_collapses_to_one_topic(repo, tmp_path):
    cfg = _make_cfg(
        tmp_path,
        feeds=[_TECHMEME_URL, _VENDOR_URL, _GNEWS_URL],
        jaccard_threshold=0.5,
        niche_gate_enabled=False,
        hn_enabled=True,
        hn_topic_source_enabled=True,
    )
    fake_parse = _make_parse({
        _TECHMEME_URL: [_entry("Anthropic launches Claude Opus 5", "https://techmeme.com/story-a")],
        _VENDOR_URL:   [_entry("Claude Opus 5 launches with major upgrades", "https://openai.com/unrelated-mirror-b")],
        _GNEWS_URL:    [_entry("Anthropic Claude Opus 5 debut", "https://news.google.com/story-c")],
    })
    hn_items = [HnItem(title="Anthropic's Claude Opus 5 is here", url="https://news.ycombinator.com/item?id=99")]

    result = fetch_unscripted_topics(
        cfg, repo,
        _parse=fake_parse,
        _now=lambda: _NOW,
        _fetch_hn=lambda cfg_arg: hn_items,
    )

    assert len(result) == 1, f"expected 1 collapsed Topic, got {len(result)}: {result}"
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1


def test_distinct_stories_from_aggregators_and_vendor_not_over_collapsed(repo, tmp_path):
    """Guard against an overly-aggressive fix: genuinely different stories
    arriving via the same set of sources must still both persist."""
    cfg = _make_cfg(
        tmp_path,
        feeds=[_TECHMEME_URL, _VENDOR_URL],
        jaccard_threshold=0.6,
        niche_gate_enabled=False,
        hn_enabled=True,
        hn_topic_source_enabled=True,
    )
    fake_parse = _make_parse({
        _TECHMEME_URL: [_entry("Anthropic launches Claude Opus 5", "https://techmeme.com/story-a")],
        _VENDOR_URL:   [_entry("Llama 5 benchmark results published", "https://openai.com/story-b")],
    })
    hn_items = [HnItem(title="New flagship GPU announced at keynote", url="https://ex/gpu")]

    result = fetch_unscripted_topics(
        cfg, repo,
        _parse=fake_parse,
        _now=lambda: _NOW,
        _fetch_hn=lambda cfg_arg: hn_items,
    )
    assert len(result) == 3


# ---------------------------------------------------------------------------
# INV-12 — down / slow / malformed feed skipped, run completes
# ---------------------------------------------------------------------------


def test_down_feed_skipped_others_still_ingest(repo, tmp_path):
    healthy_url = _VENDOR_URL
    cfg = _make_cfg(tmp_path, feeds=[_TECHMEME_URL, healthy_url, _GNEWS_URL])

    def _parse(url, **kwargs):
        if url == _TECHMEME_URL:
            raise TimeoutError("techmeme feed timed out")
        if url == _GNEWS_URL:
            raise ValueError("malformed XML")
        if url == healthy_url:
            return _feed([_entry("Llama 5 released", "https://example.com/llama5")])
        return _feed([])

    result = fetch_unscripted_topics(cfg, repo, _parse=_parse, _now=lambda: _NOW)

    assert len(result) == 1
    assert result[0]["title"] == "Llama 5 released"
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1


def test_hn_fetch_failure_skipped_rss_still_ingests(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[_VENDOR_URL], hn_enabled=True, hn_topic_source_enabled=True)
    fake_parse = _make_parse({_VENDOR_URL: [_entry("Llama 5 released", "https://example.com/llama5")]})

    def _boom(cfg_arg):
        raise ConnectionError("hn down")

    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, _fetch_hn=_boom,
    )
    assert len(result) == 1
    assert result[0]["title"] == "Llama 5 released"


# ---------------------------------------------------------------------------
# ADR-0004 niche gate still rejects off-niche items from the new aggregators
# ---------------------------------------------------------------------------


def test_off_niche_item_from_techmeme_rejected(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[_TECHMEME_URL], niche_gate_enabled=True)

    def _classify(title, summary, *, model):
        from src.topic_ingest.niche_gate import NicheVerdict
        if "Celebrity" in title:
            return NicheVerdict("off_niche", "culture entertainment", False)
        return NicheVerdict("on_niche", "ai launch", False)

    fake_parse = _make_parse({_TECHMEME_URL: [
        _entry("Celebrity feud goes viral online", "https://techmeme.com/off-niche"),
        _entry("New AI model tops benchmark", "https://techmeme.com/on-niche"),
    ]})
    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, _classify_niche=_classify,
    )
    assert len(result) == 1
    assert result[0]["title"] == "New AI model tops benchmark"


def test_off_niche_item_from_hn_rejected(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[], niche_gate_enabled=True, hn_enabled=True, hn_topic_source_enabled=True)

    def _classify(title, summary, *, model):
        from src.topic_ingest.niche_gate import NicheVerdict
        if "celebrity" in title.lower():
            return NicheVerdict("off_niche", "culture entertainment", False)
        return NicheVerdict("on_niche", "ai launch", False)

    hn_items = [
        HnItem(title="Celebrity gossip trends on front page", url="https://ex/off"),
        HnItem(title="New open-source AI model released", url="https://ex/on"),
    ]
    result = fetch_unscripted_topics(
        cfg, repo, _parse=_make_parse({}), _now=lambda: _NOW,
        _classify_niche=_classify, _fetch_hn=lambda cfg_arg: hn_items,
    )
    assert len(result) == 1
    assert result[0]["title"] == "New open-source AI model released"


def test_off_niche_item_from_google_news_rejected(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[_GNEWS_URL], niche_gate_enabled=True)

    def _classify(title, summary, *, model):
        from src.topic_ingest.niche_gate import NicheVerdict
        if "lawsuit" in title.lower():
            return NicheVerdict("off_niche", "industry drama", False)
        return NicheVerdict("on_niche", "ai launch", False)

    fake_parse = _make_parse({_GNEWS_URL: [
        _entry("Tech giant faces antitrust lawsuit", "https://news.google.com/off-niche"),
        _entry("Flagship phone ships with on-device AI model", "https://news.google.com/on-niche"),
    ]})
    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, _classify_niche=_classify,
    )
    assert len(result) == 1
    assert result[0]["title"] == "Flagship phone ships with on-device AI model"
