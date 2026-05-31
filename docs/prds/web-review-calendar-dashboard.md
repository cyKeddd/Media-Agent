# Web Review / Calendar Dashboard (v1, read-only)

**Status:** ready-for-agent
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-31
**Source session:** /grill-with-docs → /to-prd
**Decisions of record:** `CONTEXT/Grilling/2026-05-31-web-review-dashboard.md`,
`CONTEXT/CONTEXT.md` (glossary: **Review stage**)

---

## Problem Statement

My pipeline now runs autonomously on a Tue/Thu cadence, but the only way I can see what
it's doing is by opening `output/` folders in Explorer and squinting at MP4 filenames, or
by querying SQLite by hand. I can't easily answer the questions I care about: *What clip
is waiting for my approval right now? What does it actually look like? What's scheduled to
publish this week, and on which days? What's already gone live? How much have I spent
against my budget?* I want one screen that shows all of that, including a calendar of
upcoming publishes and a way to watch each clip before it goes out.

## Solution

A small **local, read-only** web dashboard I launch on my own machine
(`python -m src.dashboard`, opens on `127.0.0.1`) that reconciles the `clips` table with
the `output/` folders and shows me, on one page:

1. **Review queue** — the clips awaiting my approval (file in `output/pending/`), each with
   an in-browser video preview, its title, hook, content kind, and the Tue/Thu slot it's
   headed for.
2. **Calendar** — a month/week grid of `publish_at_utc` (shown in Asia/Singapore time),
   color-coded by **Review stage**, so I can see what publishes when.
3. **Uploaded / published list** — clips that have a `youtube_video_id`, linking out to the
   YouTube video, marked live or scheduled-on-YouTube.
4. **Status + spend header** — counts per stage, OpenRouter spend today / this week against
   my 250¢-per-clip and 500¢-daily caps, and how many `unscripted` topics are queued.

v1 is **read-only**: it never writes to the DB or moves a file. The drag-to-approve
filesystem gate stays exactly as it is — the dashboard just lets me *see* the pipeline.
Approving from the UI is v2; rescheduling / triggering runs and LAN access are v3+.

## User Stories

### Review queue + preview

1. As the channel owner, I want to see every clip currently awaiting my review (file in
   `output/pending/`), so that I know what needs my attention before its slot.
2. As the channel owner, I want to play each pending clip in the browser, so that I can
   judge it without opening a file manager or a separate player.
3. As the channel owner, I want each review-queue item to show its title, hook, and content
   kind, so that I have context beyond the filename.
4. As the channel owner, I want each pending clip to show the Tue/Thu slot
   (`publish_at_utc`, local time) it's scheduled for, so that I know how urgent the review
   is.
5. As the channel owner, I want the clip's file located by scanning the `output/` dirs, so
   that a stale `output_path` in the DB never points the preview at the wrong (or a moved)
   file.
6. As the channel owner, I want to see whether a clip is a **Hybrid clip** / its shot mix
   if that data is available, so that I can sanity-check the real-image vs AI-video balance.

### Calendar

7. As the channel owner, I want a calendar grid of upcoming publishes by `publish_at_utc`,
   so that I can see what goes out on which day at a glance.
8. As the channel owner, I want the calendar rendered in Asia/Singapore time, so that the
   days/times match the cadence I configured.
9. As the channel owner, I want calendar entries color-coded by **Review stage** (awaiting
   review / approved-scheduled / published), so that I can distinguish what's confirmed
   from what still needs me.
10. As the channel owner, I want to navigate weeks/months, so that I can see both this
    week's plan and what's already published.
11. As the channel owner, I want to click a calendar entry to jump to that clip's detail
    (preview / YouTube link), so that the calendar is a navigation surface, not just a
    picture.

### Uploaded / published list

12. As the channel owner, I want a list of clips that have a `youtube_video_id`, so that I
    can see everything that has shipped.
13. As the channel owner, I want each uploaded clip to link to its YouTube video, so that I
    can open it in one click.
14. As the channel owner, I want to see whether an uploaded clip is already live or still
    scheduled-on-YouTube (publish time past vs future), so that I understand its state.

### Status + spend header

15. As the channel owner, I want a count of clips in each **Review stage**, so that I have
    a one-glance picture of the pipeline.
16. As the channel owner, I want OpenRouter spend today and this week shown against my 250¢
    per-clip and 500¢ daily caps, so that I can watch the budget without opening the DB.
17. As the channel owner, I want per-clip cost shown when it's attributable (via the
    script's OpenRouter charges), and the aggregate spend always shown, so that the header
    is useful even before per-clip attribution exists for a given clip.
18. As the channel owner, I want the count of queued `unscripted` topics, so that I know
    whether the pipeline has material for the next run.

### Operational / safety

19. As the channel owner, I want to launch the dashboard with one command
    (`python -m src.dashboard`), so that starting it is trivial.
20. As the channel owner, I want it bound to `127.0.0.1` only, so that nothing on my
    network can reach it (the localhost bind is the security boundary; there is no auth).
21. As the channel owner, I want the dashboard to never write to the DB or move any file,
    so that it can never corrupt the pipeline or the drag-to-approve gate.
22. As the channel owner, I want a manual Refresh, so that I can pull the current state on
    demand (the data changes slowly — weekly gen_run, daily upload).
23. As the channel owner, I want the video-serving endpoint restricted to files under
    `output/`, so that the dashboard can't be coaxed into serving arbitrary files off my
    disk.
24. As a developer, I want the view-model that reconciles DB + filesystem into the four
    sections to be a pure function over injected dependencies, so that I can unit-test every
    **Review stage** derivation with fakes — no server, no real DB, no network.
25. As a developer, I want the web layer to be a thin wrapper over that view-model, so that
    almost all the logic is testable without HTTP.

## Implementation Decisions

Locked in the grill record (D1–D5). Summary:

1. **v1 is read-only; the write path is deferred.** Approve/reject from the UI is **v2**;
   reschedule slots / trigger `gen_run` / edit titles is **v3+**; LAN exposure + token auth
   is a later version. v1 never writes — the filesystem drag-to-approve gate remains the
   authoritative HITL mechanism.
2. **Stack: FastAPI + uvicorn + one static HTML/JS page.** A JSON endpoint serves the
   view-model; the static page renders the calendar, review-queue cards (`<video>`),
   uploaded list, and header. MP4 streaming is a range-aware endpoint **restricted to the
   `output/` directories**.
3. **The view-model is the keystone deep module.** A pure function —
   `build_dashboard_view(reader, scanner, now, tz) -> DashboardView` — takes an injected
   `reader` (Repository read methods) and `scanner` (output-dir lister), and returns the
   assembled four-section view. No HTTP, no real DB, no filesystem inside the unit.
4. **Review stage is derived, not stored.** For each **Clip**, the view-model reconciles
   *which `output/` directory currently holds the file* (from the scanner) with the DB
   fields (`status`, `publish_at_utc`, `youtube_video_id`) to assign one of: **Awaiting
   review** (pending/), **Approved / scheduled** (approved/ + publish set, not uploaded),
   **Published** (`youtube_video_id` set), **Rejected** (`status=rejected_*` or in
   rejected/). The file is located by **scanning**, never by trusting `clips.output_path`
   (the drag moves it). New glossary term added to `CONTEXT.md`.
5. **Spend: best-effort per-clip, always-on aggregate.** Per-clip cost via
   `quota_script_total(script_id)`; aggregate today/week via `quota_today_total(provider='openrouter')`.
   Shown against `per_clip_cost_cents_max` (250¢) and `daily_spend_cents_ceiling` (500¢).
6. **Repository gains ~2 read-only helpers.** List clips that have a `publish_at_utc` (for
   the calendar + lists); count topics by status (queue depth). Read-only SELECTs; no
   schema change. Existing `clips_by_status`, `get_clip_with_script`, `quota_script_total`,
   `quota_today_total` are reused.
7. **Launch + bind.** `python -m src.dashboard` starts uvicorn bound to `127.0.0.1` on a
   documented port; no auth. No new billed calls; no Kling; no pipeline invocation.

## Testing Decisions

### What makes a good test here

Test external behavior at the view-model boundary with injected fakes — never a real DB,
a real filesystem (beyond a temp dir for the scanner), an HTTP server, or the network. A
good test asserts *what the view-model decides* (each clip's **Review stage**, the calendar
grouping, the spend summary), not how it's wired. This is read-only software, so there is
no spend or video-generation path to guard — but consistent with the project rule, no test
invokes any billed or generation code.

### Modules under test

| Module | Test asserts |
|--------|--------------|
| **M1** view-model (`build_dashboard_view`) | Inject a fake reader + fake scanner. File in `pending/` → Awaiting review; in `approved/` + `publish_at_utc` set + no video id → Approved/scheduled; `youtube_video_id` set → Published; `status=rejected_*` → Rejected. A stale `output_path` is ignored — stage follows the scanned location. Calendar entries grouped by local-TZ date. Status counts and spend summary (per-clip best-effort + aggregate) computed correctly. |
| **M1a** output-dir scanner (`scan_output_dirs`) | Against a temp dir tree, returns the correct clip→(dir, path) mapping across pending/approved/rejected/dry_run; ignores non-MP4s; handles a clip present in no dir. |
| **M2** FastAPI app (smoke) | A `TestClient` request to the view endpoint returns 200 and the expected JSON shape; the MP4 endpoint serves a file inside `output/` and **refuses a path outside `output/`** (path-traversal guard). No real browser. |

### Prior art

- The Issue 39 backfill tests and the niche-gate tests — injected-fake discipline for a
  pure function over a data source.
- `tests/test_hybrid_gen_run.py` — patched dependencies, asserting decisions not wiring.
- FastAPI's `TestClient` is the standard for the M2 smoke test (no running server).

## Out of Scope

- **Approve / reject from the UI (v2).** Any action that moves a file pending→approved or
  →rejected, or writes clip state. v1 stays read-only.
- **Reschedule slots, trigger `gen_run`/`--dry-run`, edit titles (v3+).**
- **LAN exposure + token auth (later version).** v1 is `127.0.0.1` only.
- **Any DB or filesystem write**, and any invocation of billed/generation pipeline stages.
- **Auth / multi-user.** Single operator, localhost.
- **Replacing the drag-to-approve HITL gate** — it remains authoritative.

## Further Notes

- The dashboard is observability over the existing data; it introduces no new source of
  truth. **Review stage** is derived on every request, not persisted.
- The read-only-by-construction design (pure view-model + injected read methods +
  output/-restricted file serving + localhost bind) is what makes v1 safe to build before
  the v2 write path; the v2 approve action will be a deliberate, separately-grilled slice
  because it touches the load-bearing HITL gate that `daily_upload` depends on.
- Because the Repository self-migrates on open (e.g. `quota_usage.script_id`), the dashboard
  reuses Repository read methods rather than opening a hand-rolled read-only connection;
  the read-only guarantee is enforced by *calling only read methods* and never wiring a
  write.
