# Issue 56 — Edit title Operator override (sets title + hook, renames slug)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS3 (v3.1). Decisions of record:
`docs/adr/0007-dashboard-may-mutate-prepublication-fields.md`,
`CONTEXT/CONTEXT.md` (glossary: **Operator override**, **Clip**).

## What to build

The second **Operator override**: edit a non-published **Clip**'s title from the UI such that it
becomes the **actual published YouTube title** and the file's slug is renamed to match. Reuses
the override machinery from Issue 55 (lock wrapper, `MutationPlan`, DB-first+`os.replace`,
response shape).

End-to-end behavior:

- `clip_mutation` gains `plan_edit_title(clip_row, new_title, clip_id) -> MutationPlan | Refusal`.
  Because the uploader builds the title as `build_title(hook, suggested_title)` where `hook`
  dominates, the plan writes the new text to **both** `suggested_title` **and** `hook` (and
  updates `title_slug`), so the edited text deterministically becomes the upload title. The
  rename target reuses `editor/slug.py::title_slug`.
- Refusal: the **Clip** is published (`youtube_video_id` set).
- A `POST /api/clip/{clip_id}/edit-title` endpoint: same guardrails as reschedule — acquire
  `data/.weekly_run.lock` non-blocking (`409` if held), apply **DB-first then `os.replace`**,
  gated by `human_review`, localhost only.
- The review-queue UI gains an edit-title control that posts the new title and re-fetches.

## Acceptance criteria

- [ ] `plan_edit_title` produces a plan that sets `suggested_title` **and** `hook` to the new
      text and updates `title_slug` + the rename target; refuses a published clip.
- [ ] After a successful edit, `build_title` would yield the edited text (hook no longer
      overrides it with stale content).
- [ ] The endpoint returns `409` when the lock is held; otherwise applies DB-first then renames
      the file; refuses (`403`) when `human_review` is off; localhost-only.
- [ ] Tests: unit over `plan_edit_title` (title+hook+slug updates, published-refusal, rename
      target); endpoint tests for `409`-on-lock, DB-first success, `403` when review off,
      published-clip refusal.

## Blocked by

- Issue 55 — Operator override infrastructure + reschedule slot (provides the lock wrapper,
  `MutationPlan`/refusal types, DB-first+rename application, and response shape this reuses).
