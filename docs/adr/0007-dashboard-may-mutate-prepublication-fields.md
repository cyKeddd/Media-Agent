# ADR-0007 — The dashboard may mutate a constrained set of pre-publication clip fields (extends ADR-0006)

**Status:** Accepted
**Date:** 2026-06-06
**Context:** Surfaced while grilling the dashboard **v3.1** operator controls
(`/grill-with-docs`, 2026-06-06 next-work backlog session). Builds directly on
[ADR-0006](0006-dashboard-approve-reject-moves-files-only.md).

## Context

ADR-0006 deliberately limited the dashboard's only write to a **file move** (approve/reject),
keeping the filesystem the single HITL source of truth and the dashboard's safety story
"every write is a constrained file move, never a DB mutation." v3.1 adds two operator
controls that genuinely require DB mutation **and** a file rename:

- **Reschedule slot** — change a **Clip**'s `publish_at_utc` / `publish_slot_local` and rename
  the file whose name encodes the date + slot (`{date}__slot_{HHMM}__{slug}.mp4`).
- **Edit title** — change the effective upload title (`suggested_title` + `hook`) and rename
  the file whose name encodes the title `slug`.

These cross the line ADR-0006 drew. The dashboard also shares `state.db` and the `output/`
tree with `gen_run` / `daily_upload`, which Task Scheduler can fire at any time and which
serialize via `data/.weekly_run.lock` — a lock the dashboard never took.

## Decision

**The dashboard may mutate a constrained set of pre-publication clip fields** — scheduling
(`publish_at_utc`, `publish_slot_local`) and title (`suggested_title`, `hook`, `title_slug`) —
performing the corresponding `output/` file rename. ADR-0006's file-move-only rule still
governs approve/reject; this ADR is the narrow, deliberate exception for operator overrides.

Guardrails:
- **Non-published clips only.** Refuse if `youtube_video_id` is set — once uploaded, `publishAt`
  and title live on YouTube and a local mutation is a lie.
- **Run-lock guarded.** Each mutation acquires `data/.weekly_run.lock` **non-blocking**; if a
  pipeline run holds it, the endpoint refuses with `409 — a pipeline run is in progress`.
  Mutations never interleave with a billed run or an upload.
- **DB-first, then rename** — mirroring `slot_planner`'s invariant, so `reconcile_slot_renames`
  heals a crash between the write and the rename.
- **Reschedule** is free-form future datetime (tz-aware, snapped to :00/:30, `> now + 20 min`
  pad like the planner); a slot another non-published clip holds is **warned, not blocked**.
- **Edit title** writes the new text to `suggested_title` **and** clears/overrides `hook` so
  `build_title` deterministically yields the edited title at upload.
- **Localhost only.** These endpoints are reachable on `127.0.0.1` only; exposing them on the
  LAN is deferred to v3.2 and gated on token auth (not in this slice).

## Consequences

**Positive:**
- The operator can fix a bad slot or title in the UI before approving, instead of editing the
  DB + renaming files by hand.
- The run-lock + non-published + DB-first guardrails keep the shared-state races benign on a
  single machine.

**Negative:**
- The dashboard's "only ever moves files" simplicity (ADR-0006) is gone for these two actions;
  the safety story is now "constrained file move **or** a guarded, non-published-only,
  lock-held DB+rename." Reviewers must keep the guardrails intact.
- Two more write actors on `clips` scheduling/title fields (dashboard + `gen_run`/`slot_planner`).

## Alternatives considered

1. **Keep ADR-0006 absolute; do reschedule/edit via the DB by hand.** Rejected: defeats the
   purpose of the control panel.
2. **No run lock, rely on DB-first + reconcilers only.** Rejected during the grill: a reschedule
   could race a `daily_upload` mid-reading the same row; the lock is cheap insurance.

## References

- [ADR-0006](0006-dashboard-approve-reject-moves-files-only.md) — file-move-only approve/reject.
- `CONTEXT/CONTEXT.md` — **Review stage**, **Operator override**.
- `src/dashboard/app.py`, `src/slot_planner/runner.py` (rename + reconcile machinery),
  `src/observability/run_lock.py`, `src/uploader/templater.py` (`build_title`).
- Deferred to **v3.2**: trigger `gen_run` from the UI; LAN exposure + token auth.
