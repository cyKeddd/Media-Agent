# Issue 54 — Next-run countdown on the health band (read-only)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS3 (v3.1). Decisions of record:
`CONTEXT/CONTEXT.md` (glossary: **Run**, **Pipeline health**), `docs/adr/0007-…` (v3.1 scope).

## What to build

A read-only display of when the next scheduled generation and daily **Run** will fire, with a
live countdown, on the dashboard health band. No triggering — display only (triggering `gen_run`
is deferred to v3.2).

End-to-end behavior:

- A pure next-run module: given the configured schedule (weekly Sunday 02:00 SGT, daily 09:00
  SGT — the cadence encoded in the Task Scheduler XMLs / config) and a `now`, computes the next
  fire datetime for each **Run** kind, tz-aware in `Asia/Singapore`.
- The view-model gains a `next_run` field per kind (next-fire timestamp, served in the
  `/api/view` JSON).
- The static UI shows, on the health band, the next generation and next daily Run times plus a
  countdown that ticks client-side off the served timestamps (no new server poll).

## Acceptance criteria

- [ ] The next-run module returns the correct next fire datetime per kind for a range of fixed
      `now` inputs, including crossing a day boundary and a week boundary.
- [ ] `/api/view` includes a `next_run` entry per kind with a tz-correct timestamp.
- [ ] The health band renders both next-Run times and a live countdown that updates without an
      extra server request.
- [ ] No trigger/mutation is introduced — the feature is strictly read-only.
- [ ] Tests: unit over the next-fire computation across day/week boundaries from fixed `now`s;
      view-model includes `next_run`; an endpoint smoke that `/api/view` serves it.

## Blocked by

- None — can start immediately.
