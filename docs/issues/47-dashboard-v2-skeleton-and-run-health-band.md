# Issue 47 — Dashboard v2 skeleton + run-status health band

**Status:** complete
**Type:** AFK

## Parent

`docs/prds/dashboard-v2-health-first-redesign.md` — Dashboard v2 (health-first redesign +
approve/reject). Decisions of record: `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`
(D1–D8), `docs/adr/0005-dashboard-dependency-light-frontend.md`,
`CONTEXT/CONTEXT.md` (glossary: **Run**, **Pipeline health**, **Alert**).

## What to build

The walking skeleton of the v2 dashboard, end-to-end, plus its most important new section —
the **Pipeline health** band built from **Run** data. This slice establishes the redesigned
page so the alerts feed (Issue 48), work-area panels (Issue 49), and write path (Issue 50)
extend it.

End-to-end behavior:

- The page is re-laid-out as a **command-center** (ADR-0005, dependency-light: FastAPI +
  static files, a hand-authored CSS design system — dark refined; no Node/npm build step):
  a health-tiles row across the top, with placeholder regions below for the work area, alerts
  rail, and uploaded list that later slices fill.
- A read-only **run reader** (Repository helper, exposed via the `DashboardReader` protocol)
  returns the latest **Run** per `kind` (`generation`, `daily`) from the existing `runs`
  table — `started_at`, `finished_at`, `success`, `summary_json` — with "not yet run" when a
  kind is absent. SELECT-only; no schema change.
- The pure `build_dashboard_view` function is extended to emit a `health` section: latest
  generation **Run** tile, latest daily **Run** tile (success/failure + when + per-stage
  counts / `uploaded=N` / error string), the existing spend-vs-caps and `unscripted` queue
  figures as tiles, and a **derived overall status** — failed if the latest generation or
  daily Run failed, degraded on warning-level conditions only, healthy otherwise.
- `/api/view` returns the new `health` section in its JSON; the page renders the tiles.
- The page **auto-polls `/api/view` (~30s)** and re-renders, with a manual Refresh too.
- Launch stays `python -m src.dashboard`, bound to **127.0.0.1** only, no auth.

Read-only: no DB write, no file move, no pipeline/billed call. The health rollup stays inside
the pure view-model over injected read dependencies.

## Acceptance criteria

- [ ] `python -m src.dashboard` serves the redesigned command-center page on `127.0.0.1`
      only; no auth; no build step (static files only, ADR-0005).
- [ ] Run reader returns the latest **Run** per `kind` (and is order-correct), with a
      "not yet run" result when a kind has no rows; SELECT-only, no schema change.
- [ ] `build_dashboard_view` emits a `health` section: latest generation Run, latest daily
      Run, spend-vs-caps, `unscripted` queue depth, and a derived overall status
      (failed / degraded / healthy) per the rule above.
- [ ] `/api/view` JSON includes the `health` section; the page renders the tiles with
      semantic status colors and shows the failed Run's error string when present.
- [ ] The page auto-refreshes ~30s and on manual Refresh.
- [ ] No DB write, file move, or billed/generation call.
- [ ] Tests: **M2** run reader (latest-per-kind + ordering + empty table) against a
      fake/temp `runs` source; **M1** health rollup (injected fakes: latest-run selection +
      overall-status derivation for failed/degraded/healthy); **M5** `TestClient` smoke
      (`/api/view` 200 with the `health` shape). No real DB/server/network; no billed code.

## Blocked by

None - can start immediately.
