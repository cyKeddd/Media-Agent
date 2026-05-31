# Issue 46 — Dashboard uploaded list + status/spend header

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/web-review-calendar-dashboard.md` — Web Review / Calendar Dashboard (v1).
Decisions of record: `CONTEXT/Grilling/2026-05-31-web-review-dashboard.md` (D1–D5).

## What to build

The two remaining sections, extending the Issue 44 view-model and page: the
**uploaded/published list** and the **status + spend header**.

End-to-end behavior:

- **Uploaded list:** the view-model assembles clips that have a `youtube_video_id`, each
  with a link to its YouTube video and a flag for **live** (publish time past) vs
  **scheduled-on-YouTube** (publish time future). The page renders this as a list.
- **Status + spend header:** the view-model computes counts per **Review stage**, an
  OpenRouter spend summary (per-clip cost best-effort via `quota_script_total(script_id)`;
  aggregate today/this-week via `quota_today_total(provider='openrouter')`) shown against
  `per_clip_cost_cents_max` (250¢) and `daily_spend_cents_ceiling` (500¢), and the count of
  queued `unscripted` topics. The page renders this as a header strip.

Read-only; no writes. Reuses existing read methods (`clips_by_status`,
`quota_script_total`, `quota_today_total`) and adds a read-only Repository helper to count
topics by status.

## Acceptance criteria

- [ ] The uploaded list contains exactly the clips with a `youtube_video_id`, each linking
      to the correct YouTube video.
- [ ] Each uploaded clip is flagged live vs scheduled-on-YouTube by comparing its publish
      time to now.
- [ ] The header shows counts per **Review stage**.
- [ ] The header shows OpenRouter spend: per-clip cost when attributable (else omitted
      gracefully) and aggregate today/this-week, both against the 250¢/500¢ caps.
- [ ] The header shows the count of queued `unscripted` topics.
- [ ] Read-only — no DB write, file move, or pipeline call.
- [ ] Tests: uploaded classification (has video id → listed; live vs scheduled by publish
      time) and spend/summary aggregation (per-clip best-effort + aggregate, counts, queue
      depth) in the view-model with injected fakes. No real DB/server/network.

## Blocked by

- Issue 44 (dashboard skeleton + review queue) — provides the app, view-model, and stage
  derivation this extends. (Independent of Issue 45; 45 and 46 can proceed in parallel.)
