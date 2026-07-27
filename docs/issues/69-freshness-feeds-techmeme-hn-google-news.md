# Issue 69 — Freshness: Techmeme, HN as a topic source, Google News queries

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 3 (Medium)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS4.

## What to build

Raise topic freshness without paid X/Twitter access (explicitly deferred — see PRD non-goals).

The current seven feeds are vendor blogs plus two outlet AI subfeeds. Vendor blogs are
authoritative but slow and bursty; when they are quiet the ingest window widens 48 h → 96 h and the
channel ends up reporting week-old news. The newest **Topic** in the DB is dated 2026-07-16.

Three free additions:

- **Techmeme** (`https://www.techmeme.com/feed.xml`) — near-real-time aggregation of tech
  reporting, the single highest-freshness free source available.
- **Hacker News promoted to a topic source.** HN is already polled for **Trending corroboration**
  (`topic_ingest.hn`) but never contributes **Topics**. Front-page items passing the niche gate
  should become candidate **Topics**. Reuse the existing HN client — do not add a second one.
- **Google News RSS keyword queries**, AI-scoped, e.g.
  `https://news.google.com/rss/search?q=%22AI+model%22+when:1d&hl=en-US&gl=US&ceid=US:en`.
  Two or three narrow queries, not one broad one.

Scope:

- Feeds added to `config.yaml` (`topic_ingest.feeds`) and documented in `docs/rss_feeds.md` with a
  rationale line each, matching the existing table format.
- `scripter.source_authority` weights for the new sources: aggregators rank **below** primary
  vendor blogs. Techmeme/HN/Google News surface a story early; the vendor blog remains the
  authority for what the narration asserts.
- The on-niche ingest gate (ADR-0004) does more work now that rumour-carrying aggregators are in
  the mix — confirm it still rejects off-niche items from these sources specifically.
- Dedup must collapse the same story arriving via Techmeme, HN, Google News, *and* the vendor blog
  into **one Topic** — this is the main risk of adding aggregators, since they all cover the same
  launches. Existing dedup is URL hash + normalised-title similarity; verify it holds when the same
  story has four different URLs and four differently-worded headlines.
- Only after volume is demonstrably healthy, narrow `recency_hours` 48 → 24. Leave the change
  configured but do not enable it in this issue.

## Invariants

- **INV-12** — A feed that is down, slow, or returns malformed XML must not fail the run: log,
  skip that feed, continue with the others.
- Existing (ADR-0004): off-niche items are rejected at ingest before persisting.

## Acceptance criteria

- [ ] Techmeme, an HN-sourced path, and 2–3 Google News keyword queries are configured and
      documented in `docs/rss_feeds.md`.
- [ ] HN front-page items passing the niche gate are persisted as **Topics**, reusing the existing
      HN client.
- [ ] HN items still contribute **Trending corroboration** — the new source role does not break the
      existing ranking role (regression guard).
- [ ] `source_authority` ranks aggregators below primary vendor blogs.
- [ ] The same story arriving from four sources with four URLs and four headline wordings produces
      exactly **one Topic**.
- [ ] A feed returning a 500, a timeout, or malformed XML is skipped with a log line; the run
      completes and other feeds still ingest.
- [ ] An off-niche item from Techmeme/HN/Google News is rejected by the niche gate.
- [ ] Tests use fixture feed payloads — **no live network calls.**

## Blocked by

- None — independent, safe to run in parallel.

## Verification-command

```
pytest tests/test_topic_ingest_freshness_feeds.py -q
```
