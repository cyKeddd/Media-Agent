# Dashboard v2 — Health-first redesign + in-UI approve/reject

**Status:** complete
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-06-01
**Source session:** /grill-with-docs → /to-prd
**Decisions of record:** `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`,
`docs/adr/0005-dashboard-dependency-light-frontend.md`,
`docs/adr/0006-dashboard-approve-reject-moves-files-only.md`,
`CONTEXT/CONTEXT.md` (glossary: **Run**, **Pipeline health**, **Alert**, **Approve / Reject action**)
**Supersedes scope of:** the deferred "v2 = approve/reject" line in
`docs/prds/web-review-calendar-dashboard.md`

---

## Problem Statement

The dashboard v1 (Issues 44–46) is live at `http://127.0.0.1:8765/` and it does its read-only
job, but two things are wrong. First, **it looks bad** — three flat stacked lists on a dark
page, no visual hierarchy, nothing that reads as a console. Second, and more important, **it
can't answer the question I actually open it to ask: "is my agent OK right now?"** I can't see
whether the last weekly `gen_run` succeeded or blew up, whether today's `daily_upload` fired,
or whether anything is alerting — that information exists (the `runs` table, `logs/alerts.md`)
but the dashboard ignores all of it. And when a clip *is* waiting for me, I still have to leave
the dashboard, open Explorer, and drag the MP4 from `output/pending/` to `output/approved/` to
approve it. I want one good-looking screen that tells me the pipeline's health at a glance and
lets me approve or reject the waiting clip without leaving the page.

## Solution

A redesigned **health-first** local dashboard (still `python -m src.dashboard`, still bound to
`127.0.0.1`). The page opens on a **Pipeline health** band — the latest generation and daily
**Run** outcomes, spend against caps, queue depth, and a recent **Alerts** feed — so the first
thing I see is whether the agent is healthy. Below it, a **command-center** two-column work
area: the review queue with a large in-browser preview and **Approve / Reject** buttons on the
left, the publish calendar on the right; a slim alerts rail; and the uploaded list collapsed at
the bottom. It **auto-refreshes** (~30s) so a failure surfaces on its own, with a manual Refresh
too.

The **Approve / Reject action** is the same drag-to-approve gate, performed in the UI: it
**moves the MP4 only** (`pending/ → approved/` or `pending/ → rejected/`), never writes clip
state, so `daily_upload`'s contract is unchanged (ADR-0006). It requires a confirm step, acts
only on a file currently in `output/pending/`, moves atomically, and reject is reversible. The
buttons appear **only while `human_review` is on**; in autonomous mode the queue is read-only
with a banner, because approval gates nothing then.

The redesign is **dependency-light** (ADR-0005): FastAPI + static files, a hand-authored CSS
design system, split vanilla JS — no Node/npm build step.

## User Stories

### Pipeline health (new)

1. As the channel owner, I want the dashboard to open on a health band, so that the first thing
   I see is whether my agent is OK right now.
2. As the channel owner, I want a derived overall **Pipeline health** indicator
   (healthy / degraded / failed), so that I get a single yes/no read before I look at details.
3. As the channel owner, I want the most recent generation **Run** shown (success/failure, when
   it ran, per-stage counts, and the error string if it failed), so that I know my weekly
   `gen_run` is working without opening `logs/runs.md` or the DB.
4. As the channel owner, I want the most recent daily **Run** shown (`uploaded=N` /
   `no_candidates` / error), so that I know today's `daily_upload` fired and what it did.
5. As the channel owner, I want a feed of the most recent **Alerts** (newest first), so that I
   see loudness warnings, quota-exceeded, missed-slot recovery, and run failures as they
   accumulate.
6. As the channel owner, I want **Alerts** color-coded by severity (error / warning / info), so
   that a real failure is visually distinct from a routine notice.
7. As the channel owner, I want spend today and this week against my 250¢-per-clip and 500¢-daily
   caps shown as a health tile, so that I watch the budget at a glance.
8. As the channel owner, I want the count of queued `unscripted` **Topics** shown as a tile, so
   that I know whether the pipeline has material for the next run.
9. As the channel owner, I want the health band to update on its own (~30s poll), so that I'm
   never staring at a stale "healthy" while a **Run** has already failed.

### Review queue + approve/reject (new write path)

10. As the channel owner, I want to see every **Clip** currently **Awaiting review**
    (file in `output/pending/`), with a large in-browser preview, title, hook, content kind, and
    its Tue/Thu slot, so that I can judge it in place.
11. As the channel owner, I want an **Approve** button on each pending clip that moves its file
    to `output/approved/`, so that I can clear it for upload without opening Explorer.
12. As the channel owner, I want a **Reject** button that moves the file to `output/rejected/`,
    so that I can kill a bad clip from the UI.
13. As the channel owner, I want a confirm step before an approve or reject takes effect, so that
    a misclick can't push a clip toward YouTube.
14. As the channel owner, I want the server to act only on a file that is actually in
    `output/pending/` at action time (re-scanned), and refuse otherwise, so that a stale page
    can't double-action or act on something already moved.
15. As the channel owner, I want the file move to be atomic, so that a clip is never left in a
    half-moved state.
16. As the channel owner, I want a reject to be reversible (the clip can return to the queue), so
    that an accidental reject isn't permanent.
17. As the channel owner, I want the approve/reject controls to appear **only while
    `human_review` is on**, so that the UI never offers an action that does nothing.
18. As the channel owner, I want a clear "autonomous mode — approval disabled" banner when
    `human_review` is off, so that I understand why the queue is read-only.
19. As the channel owner, I want the queue and health to refresh after I approve/reject, so that
    the actioned clip leaves the queue and the counts update.

### Calendar (restyled, read-only)

20. As the channel owner, I want the publish calendar in the right column of the work area, so
    that I can see what publishes when alongside the review queue.
21. As the channel owner, I want calendar entries rendered in Asia/Singapore time and color-coded
    by **Review stage**, so that scheduled / live / awaiting / rejected are distinguishable.
22. As the channel owner, I want to navigate months and click an entry to jump to that clip, so
    that the calendar stays a navigation surface.

### Uploaded list (restyled, read-only)

23. As the channel owner, I want the uploaded/published list collapsed at the bottom and
    expandable, so that it's available without crowding the health-first layout.
24. As the channel owner, I want each uploaded clip to link to YouTube and show live vs
    scheduled-on-YouTube, so that I can open it and understand its state in one click.

### Look & feel

25. As the channel owner, I want a coherent dark, refined visual design (consistent spacing,
    typography, cards, semantic status colors), so that the dashboard looks good, not like a raw
    list dump.
26. As the channel owner, I want the command-center layout (health tiles on top, two-column work
    area, slim alerts rail, collapsed uploads), so that everything important is above the fold.

### Operational / safety (carried from v1, extended for the write path)

27. As the channel owner, I want to launch with one command (`python -m src.dashboard`), so that
    starting it stays trivial.
28. As the channel owner, I want it bound to `127.0.0.1` only with no auth, so that the localhost
    bind remains the security boundary (LAN + auth stay v3).
29. As the channel owner, I want every write to be a constrained file move strictly inside
    `output/` (never a DB mutation, never a file outside `output/`), so that the dashboard can't
    corrupt the DB or touch arbitrary disk.
30. As the channel owner, I want the video-serving endpoint to stay restricted to files under
    `output/` (path-traversal guarded), so that the preview can't be coaxed into serving
    arbitrary files.
31. As a developer, I want the health rollup and **Review stage** derivation to stay a pure
    function over injected read dependencies, so that every derivation is unit-testable with
    fakes — no server, no real DB, no network.
32. As a developer, I want the review-action (file-move) logic isolated in its own module over an
    injected scanner + filesystem, so that I can test the pending-only precondition, atomic move,
    and reversibility against a temp dir tree with no HTTP.

## Implementation Decisions

Locked in the grill record (D1–D8) and ADR-0005 / ADR-0006.

1. **Scope (D1).** v2 = health-first redesign **+** in-UI approve/reject. Reschedule slots,
   trigger `gen_run`/dry-run, edit titles, and LAN exposure + token auth are **v3**. The
   "next scheduled run" countdown is deferred to v3 (needs Task Scheduler query or
   cadence-derived state that can drift).

2. **Approve/Reject moves files only (D2, ADR-0006).** Approve = `pending/ → approved/`;
   Reject = `pending/ → rejected/`. No DB write, no new schema column. The filesystem stays the
   single source of truth `daily_upload` reads. `clips.status` is untouched by the action.

3. **Health rollup in the view-model (D3).** Extend `DashboardView` with a `health` section
   carrying: latest generation **Run**, latest daily **Run**, a list of recent **Alerts**, plus
   the existing spend/queue header fields and a derived overall status. The rollup stays inside
   the pure `build_dashboard_view` function. Overall status is derived: **failed** if the latest
   generation or daily Run failed; **degraded** if there are recent warning-level Alerts but no
   failed Run; **healthy** otherwise. (Exact thresholds are an implementation detail of the
   issue.)

4. **Run reader (D3).** Add read-only Repository helper(s) to fetch the latest **Run** per
   `kind` (and recent N), exposed through the `DashboardReader` protocol. SELECT-only on the
   existing `runs` table; no schema change. `runs` already has `kind`, `started_at`,
   `finished_at`, `success`, `summary_json`.

5. **Alerts parser (D3).** A module that reads the tail of `logs/alerts.md` and returns
   structured entries `{timestamp, kind, message, severity}`, newest first, with a kind→severity
   map (e.g. `gen_run_failed`→error; `loudness_warn`/`upload_quota_exceeded`→warning;
   `gen_run_finished`/`recovered_slot`/`publish_at_padded`→info). Pure over an injected file
   path, mirroring the existing `scan_output_dirs` discipline. Tolerant of the mixed historical
   line formats present in the file.

6. **Review-action module (D2, D6, ADR-0006).** A deep module
   `apply_review_action(clip_id, action, *, scanner, paths) -> ActionResult` over an injected
   output scanner + the configured pending/approved/rejected dirs. It (a) re-scans, (b) requires
   the clip's file to be in `pending/` (else returns a refused/no-op result), (c) performs an
   **atomic** `os.replace` to the approved or rejected dir, (d) for an "unreject" moves
   `rejected/ → pending/`. No billed/generation code; no DB write.

7. **FastAPI app (D6, D7).** Add POST endpoints for approve/reject (e.g.
   `POST /api/clip/{clip_id}/approve` and `/reject`) that delegate to the review-action module
   and return the action result. The endpoints (and the UI controls) are **gated on
   `human_review`** read from config — when off, the action endpoints refuse and the UI renders
   the queue read-only with a banner. The existing `/api/view` (GET) and `/api/video/...` (range
   GET, output/-restricted) remain.

8. **Auto-refresh (D5).** The static page polls `/api/view` on a ~30s interval and re-renders;
   a manual Refresh button remains. After a successful approve/reject the page re-fetches
   immediately.

9. **Frontend redesign (D4, D8, ADR-0005).** Dependency-light: FastAPI + static assets, a
   hand-authored CSS design system (design tokens, cards, typography, semantic status colors),
   and split vanilla JS modules — **no Node/npm build step**. Command-center layout: health
   tiles row → two-column work area (review queue + preview left, calendar right) → slim alerts
   rail → collapsed uploaded list. Dark, refined theme.

10. **No new billed calls.** No Kling, no `gen_run`/upload invocation. v2 adds exactly one new
    capability beyond reads: moving an MP4 between `output/` subdirs.

## Testing Decisions

### What makes a good test here

Test external behavior at module boundaries with injected fakes — never a real DB, an HTTP
server (beyond `TestClient`), the network, or any billed/generation code. For the read side,
assert *what the view-model decides* (overall health, latest-run-per-kind selection, alert
severity, **Review stage**), not how it's wired. For the write side, assert *what the
review-action module does to a temp dir tree* (the file ends up where it should, the
precondition is enforced, the move is atomic and reversible) — never the live `output/`.

### Modules under test (1–5 per the grill)

| Module | Test asserts |
|--------|--------------|
| **M1** view-model health rollup (`build_dashboard_view`) | Inject a fake reader (latest runs, alerts, spend, queue) + fake scanner. Latest generation/daily **Run** selected correctly; overall status = failed when a latest Run failed, degraded on warning Alerts only, healthy otherwise; existing **Review stage** + calendar + spend derivations still hold. |
| **M2** run reader | Latest **Run** per `kind` and recent-N returned in the right order from a fake/temp `runs` source; empty table → "not yet run". |
| **M3** alerts parser | Against a temp `alerts.md` (including the mixed historical formats), returns structured entries newest-first with the correct kind→severity mapping; tolerates malformed/blank lines; respects the tail limit. |
| **M4** review-action module | Against a temp pending/approved/rejected tree: approve moves pending→approved; reject moves pending→rejected; a clip **not** in pending → refused/no-op (no move); move is atomic (`os.replace`); unreject moves rejected→pending; never writes the DB. |
| **M5** FastAPI app (smoke) | `TestClient`: `/api/view` returns 200 with the health section in the JSON shape; POST approve moves the file in a temp tree and returns the result; with `human_review` off the action endpoint refuses; `/api/video/...` serves inside `output/` and **refuses a path outside** it. No real browser. |

Frontend (CSS/JS) is **not** unit-tested — covered by the M5 smoke test and manual `/run`
eyeballing.

### Prior art

- `tests/test_hybrid_gen_run.py` — patched dependencies, asserting decisions not wiring.
- The Issue 39 backfill tests and niche-gate tests — injected-fake discipline over a data
  source.
- The v1 dashboard tests (Issues 44–46) — the existing `build_dashboard_view` /
  `scan_output_dirs` / `TestClient` pattern this PRD extends.

## Out of Scope

- **v3 control panel:** reschedule slots, trigger `gen_run`/`--dry-run`, edit titles.
- **Next-scheduled-run countdown** (Task Scheduler query / cadence-derived) — v3.
- **LAN exposure + token auth** — v2 stays `127.0.0.1`-only, no auth.
- **Any DB write** — including any new clip status; the action moves files only (ADR-0006).
- **Any change to `daily_upload`'s contract** — it keeps reading `output/approved/`.
- **A frontend build toolchain** (Node/npm, SPA framework) — ADR-0005.
- **Editing the drag-to-approve gate itself** — the UI action *is* that gate; dragging in
  Explorer still works identically.

## Further Notes

- The redesign is observability + one constrained action over existing data; it introduces no
  new source of truth. **Pipeline health** and **Review stage** are derived on every request.
- The dashboard and `gen_run` can both write `output/` on the same machine; atomic `os.replace`
  plus the pending-only precondition (Decision 6) make races benign (ADR-0006 consequences).
- Because approve/reject *is* the load-bearing HITL gate `daily_upload` depends on, the
  review-action module (M4) is the must-test unit; its precondition and atomicity are the safety
  guarantees, not UI conveniences.
