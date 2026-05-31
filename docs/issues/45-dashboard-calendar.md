# Issue 45 — Dashboard calendar of scheduled publishes

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/web-review-calendar-dashboard.md` — Web Review / Calendar Dashboard (v1).
Decisions of record: `CONTEXT/Grilling/2026-05-31-web-review-dashboard.md` (D1–D5).

## What to build

The calendar section, extending the Issue 44 view-model and page. A month/week grid that
plots every **Clip** with a `publish_at_utc`, so the owner can see what publishes on which
day at a glance.

End-to-end behavior:

- The view-model gains calendar entries: each clip with a `publish_at_utc`, grouped by its
  **local (Asia/Singapore) date**, carrying its derived **Review stage**, title, and slot
  time.
- The page renders a calendar grid (navigable across weeks/months) with entries
  **color-coded by Review stage** (awaiting review / approved-scheduled / published).
- Clicking a calendar entry navigates to that clip's detail (its review-queue preview or,
  once Issue 46 lands, its uploaded entry / YouTube link).

Read-only; no writes. Reuses the existing pure view-model + injected dependencies; adds a
read-only Repository helper to list clips that have a `publish_at_utc` if one isn't already
available.

## Acceptance criteria

- [ ] The view-model returns calendar entries grouped by local (Asia/Singapore) date, each
      carrying the clip's derived **Review stage**, title, and slot time.
- [ ] The page renders a navigable calendar grid (week/month) showing those entries on the
      correct local days.
- [ ] Entries are color-coded by **Review stage**.
- [ ] Clicking an entry navigates to that clip's detail/preview.
- [ ] Read-only — no DB write, file move, or pipeline call.
- [ ] Tests: calendar grouping/derivation in the view-model with injected fakes
      (UTC→Asia/Singapore date bucketing, stage carried through). No real DB/server/network.

## Blocked by

- Issue 44 (dashboard skeleton + review queue) — provides the app, view-model, and stage
  derivation this extends.
