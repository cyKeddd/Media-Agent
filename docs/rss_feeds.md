# RSS feed list — AI-centric topic ingest (ADR-0004)

Curated feeds for `topic_ingest.feeds` in `config.yaml`. Primary-source AI lab/vendor blogs plus AI-specific subfeeds from major outlets — less culture/think-piece noise at the source. The on-niche ingest gate (Issue 31) is the backstop.

| Feed URL | Rationale |
|---|---|
| `https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml` | Anthropic news/launches (community RSS mirror — Anthropic has no official feed). Primary source for Claude/Opus stories. |
| `https://blog.google/technology/ai/rss/` | Google AI blog — Gemini, on-device AI, research releases. |
| `https://openai.com/blog/rss.xml` | Primary-source OpenAI model and product announcements. |
| `https://deepmind.google/blog/rss.xml` | Google DeepMind research posts. |
| `https://huggingface.co/blog/feed.xml` | Open-source ML tooling and model releases. |
| `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` | The Verge **AI subfeed** (replaces main Verge feed). |
| `https://arstechnica.com/ai/feed/` | Ars Technica **AI section** (replaces technology-lab main feed). |
| `https://www.techmeme.com/feed.xml` | Near-real-time tech-reporting aggregator — the highest-freshness free source available (Issue 69). Ranked below primary vendor blogs in `scripter.source_authority`: it surfaces a story early, the vendor blog stays the authority for what the narration asserts. |
| `https://news.google.com/rss/search?q=%22AI+model%22+when:2d&hl=en-US&gl=US&ceid=US:en` | Google News RSS keyword query — AI model/research releases (Issue 69). Narrow and AI-scoped, not a broad tech query. |
| `https://news.google.com/rss/search?q=%22AI+feature%22+when:2d&hl=en-US&gl=US&ceid=US:en` | Google News RSS keyword query — AI shipping inside a product, e.g. Apple Intelligence / Copilot (Issue 69). |
| `https://news.google.com/rss/search?q=%22AI+chip%22+when:2d&hl=en-US&gl=US&ceid=US:en` | Google News RSS keyword query — flagship AI hardware (Issue 69). |

**Dropped from the pre-ADR list:** VentureBeat (enterprise think-pieces), TechCrunch (general startup noise), The Verge main feed, Ars technology-lab main feed.

## Hacker News — dual role (Issue 69)

Hacker News (`topic_ingest.hn`) is polled once through a single client
(`src/topic_ingest/hn.py`, `fetch_hn_front_page`) and serves **two roles** off
that one fetch:

1. **Trending corroboration** (pre-existing, ADR-0004) — `hn_corroboration()`
   boosts a **Topic**'s ranking during scripter Stage A when its title
   overlaps an HN front-page title. Unaffected by promotion to a topic
   source below — same function, same call site.
2. **Topic source** (Issue 69, `topic_ingest.hn.topic_source_enabled: true`)
   — HN front-page items that pass the on-niche ingest gate are persisted as
   candidate **Topics** in their own right, tagged with `source_feed:
   "hacker-news"` and ranked below primary vendor blogs in
   `scripter.source_authority` (same rationale as Techmeme above).

Do not add a second HN client for either role.

## Setup notes

- Feeds are read by `src/topic_ingest/runner.py` with a 48 h recency window (configurable via `topic_ingest.recency_hours`; widens to 96 h on low on-niche yield). Narrowing to 24 h is deferred (Issue 69) until freshness-feed volume is demonstrably healthy — left configured-but-off, not enabled.
- Dedup is URL hash + normalized-title similarity — the same story across feeds (including Techmeme, HN, and Google News duplicating a vendor-blog story under four different URLs and headline wordings) is collapsed to one **Topic**.
- Off-niche items are rejected by the ingest niche gate before persisting (`topic_ingest.niche_gate`), including items arriving via Techmeme, HN, or Google News specifically.
- Hacker News front-page corroboration boosts ranking during scripter Stage A (`topic_ingest.hn`) — see dual-role note above.
- Add or remove feeds in `config.yaml` only; no code change required. Prefer stable RSS/Atom endpoints with English content.
