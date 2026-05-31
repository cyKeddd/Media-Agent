# Grill record — web review/calendar dashboard (v1)

**Date:** 2026-05-31
**Trigger:** Steady-state autonomy path shipped (Issues 39–43); the web review/calendar
dashboard was the deferred next-up follow-on. User asked to grill it, then
`/to-prd → /to-issues → /handoff → /push-on-task-complete`.
**Mode:** `/grill-with-docs`. User delegated most calls ("do the recommended") and set the
version roadmap.

## What the dashboard is for

A local tool to **see and review what will be uploaded, what is scheduled, and a calendar**
of upcoming publishes — visibility into the autonomous pipeline the user otherwise only
sees as MP4 files in `output/` folders.

## Verified code facts (this grill)

- **The pending/approved HITL gate is filesystem, not DB.** `clips.status` values seen:
  `cancelled`, `rejected_policy`, `rejected_quality`, `uploaded` — there is **no
  pending/approved status**. A **Clip** awaiting sign-off is just an MP4 in
  `output/pending/`; the operator drags it to `output/approved/` and `daily_upload` trusts
  that. So the dashboard must **reconcile DB rows with the `output/` dir** that holds the
  file, and must **locate the file by scanning** (the drag moves it, so `clips.output_path`
  can be stale).
- **No web framework installed** (no FastAPI/Flask/Streamlit/uvicorn) — greenfield stack.
- **Per-clip cost attribution works** via the Repository: `quota_usage.script_id` exists
  in `schema.sql` and is added lazily by `_ensure_quota_script_id_column` on connection
  open; `quota_script_total(script_id)` returns per-clip OpenRouter cents. A raw
  `sqlite3.connect` (bypassing Repository) doesn't show the column — not a bug, just the
  lazy migration. Aggregate spend via `today_total()` always works.
- **Clip fields available:** `publish_at_utc`, `publish_slot_local`, `output_path`,
  `youtube_video_id`, `content_kind`, `script_id`, `suggested_title`, `hook`, `status`.
- TZ `Asia/Singapore`; slots `09:00/13:00/17:00/21:00`.

## Decisions locked

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **v1 = read-only viewer + calendar + preview.** Approve/reject action = **v2**; control panel (reschedule, trigger gen_run, edit titles) + LAN exposure = **v3+**. | Smallest safe slice; the approve path writes to the load-bearing HITL gate `daily_upload` depends on, so it deserves its own slice. |
| D2 | **Stack = FastAPI + uvicorn + one static HTML page.** The reconciliation logic is a **pure view-model deep module** over an injected data source. | Data layer is unit-testable with a fake repo/fs (no server, no real DB); native MP4 serving; minimal deps; fits the project's deep-module + injected-fake discipline. |
| D3 | **Four v1 sections:** (1) Review queue + in-browser `<video>` preview; (2) Calendar of `publish_at_utc` (local TZ), color-coded by stage; (3) Uploaded/published list with YouTube links; (4) Status + spend header (counts per stage, OpenRouter spend today/week vs caps, queue depth). | Covers "what will be uploaded / what's scheduled / the calendar" plus budget visibility. |
| D4 | **Review stage** is derived by reconciling the `output/` dir holding the file with DB fields: Awaiting review / Approved-scheduled / Published / Rejected. File located by **scanning**, not by trusting `output_path`. New glossary term added. | `clips.status` doesn't encode the filesystem HITL position; stale `output_path` would mislead. |
| D5 | **Ops/safety:** launch `python -m src.dashboard` → uvicorn **bound to 127.0.0.1 only**, no auth (localhost bind is the boundary); **manual Refresh** (low-velocity data); view-model **never writes**; per-clip cost best-effort via `quota_script_total`, aggregate spend always available. LAN+token deferred to a later version. | Read-only by construction; no network/auth surface in v1. |

## Doc updates this session

- **CONTEXT.md** — added **Review stage** to the Ship-lifecycle glossary (the reconciled
  Clip lifecycle the dashboard surfaces).
- **No ADR** — the read-only / phasing decision is reversible (v2 adds the write path), so
  it fails the "hard to reverse" ADR test; captured here instead.

## Out of scope (v1)

Approve/reject from the UI (v2); reschedule slots, trigger gen_run/dry-run, edit titles
(v3+); LAN exposure + token auth (later); any write to DB or filesystem; replacing the
drag-to-approve HITL gate (stays authoritative in v1).
