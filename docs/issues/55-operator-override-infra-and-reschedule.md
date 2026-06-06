# Issue 55 — Operator override infrastructure + reschedule slot (ADR-0007)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS3 (v3.1). Decisions of record:
`docs/adr/0007-dashboard-may-mutate-prepublication-fields.md`,
`CONTEXT/CONTEXT.md` (glossary: **Operator override**, **Review stage**, **Clip**).

## What to build

The dashboard's first **Operator override** — the first time it writes the DB (ADR-0007 extends
ADR-0006's file-move-only rule). This slice builds the **shared override machinery** and the
**reschedule slot** action on top of it. (Edit-title, Issue 56, reuses this machinery.)

End-to-end behavior:

- A deep `clip_mutation` core (sibling to the review-action module), pure and injectable:
  `plan_reschedule(clip_row, new_dt, tz, now) -> MutationPlan | Refusal`. A `MutationPlan`
  carries the DB field updates (`publish_at_utc`, `publish_slot_local`) and the rename
  `(from_path, to_path)`; the rename target reuses `slot_planner`'s slot-filename builder.
- Refusals: the **Clip** is published (`youtube_video_id` set); the datetime is not
  `> now + 20 min` (the planner's pad). A slot another non-published **Clip** already holds is a
  **warning** on the plan, **not** a refusal.
- Reschedule datetime is tz-aware `Asia/Singapore`, snapped to :00/:30.
- A `POST /api/clip/{clip_id}/reschedule` endpoint: acquires `data/.weekly_run.lock`
  **non-blocking** (→ `409` "a pipeline run is in progress" if held), then applies the plan
  **DB-first, then `os.replace`** for the file rename, and returns a result (with any collision
  warning) mirroring the existing action response. Gated by `human_review` like approve/reject.
  Localhost only.
- The review-queue / calendar UI gains a reschedule control that posts the new datetime and
  re-fetches `/api/view`.

## Acceptance criteria

- [ ] `plan_reschedule` produces a plan with the right DB updates + rename target for a valid
      future datetime; refuses a published clip; refuses a datetime inside the now+20m pad;
      flags (does not refuse) a slot collision with another non-published clip.
- [ ] The endpoint returns `409` when `data/.weekly_run.lock` is held; otherwise applies
      DB-first then renames the file with `os.replace`, and the row + file reflect the new slot.
- [ ] A crash between the DB write and the rename is healed by the existing
      `reconcile_slot_renames` (the DB-recorded target is completed on the next run).
- [ ] The endpoint refuses (`403`) when `human_review` is off; the control is localhost-only.
- [ ] Tests: unit over `plan_reschedule` (valid / published-refusal / pad-refusal / collision
      warning / rename target); endpoint tests for `409`-on-lock, DB-first success, `403` when
      review off, published-clip refusal. No live YouTube/OAuth/billed calls.

## Blocked by

- None — can start immediately.
