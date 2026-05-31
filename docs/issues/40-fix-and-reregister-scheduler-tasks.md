# Issue 40 — Fix + re-register the Task Scheduler tasks

**Status:** ready-for-agent
**Type:** HITL (operator re-registers the tasks on Windows)

## Parent

`docs/prds/steady-state-autonomous-cadence.md` — Steady-State Autonomous Cadence (M2).
Decisions of record: `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md` (S6).

## What to build

The two Windows Task Scheduler definitions are stale and would crash or run the wrong
code unattended:

- `scripts/weekly_run.xml` runs `-m src.weekly_run`, a module renamed to `gen_run` (the
  `gen_run_failed ModuleNotFoundError` rows in `logs/alerts.md` are exactly this).
- Both `weekly_run.xml` and `daily_upload.xml` point their `.venv` python at
  `C:\Users\cryptix\Documents\Media-Agent-main` — a stale second copy of the repo — not
  the live `C:\Users\cryptix\Desktop\Work\Media-Agent-main` tree that is actually shipped.

Fix the XMLs and re-register both tasks so the scheduler runs the correct module from the
correct tree:

- `weekly_run.xml`: `Arguments` → `-m src.gen_run --clips 2` (explicit, budget-bounded
  count); `Command` python path → the `Desktop\Work\Media-Agent-main\.venv` python.
- `daily_upload.xml`: `Command` python path → the `Desktop\Work` tree's `.venv` python.
- Re-register both scheduled tasks so the corrections take effect.
- Confirm the weekly trigger is the intended day (Sunday 02:00 SGT) and the daily trigger
  is daily 09:00 SGT.

This is config + a deploy step, not application code. Whether to delete the stale
`Documents\` copy entirely is a separate operator decision (Further Notes in the PRD) and
out of scope here.

## Acceptance criteria

- [ ] `weekly_run.xml` `Arguments` reads `-m src.gen_run --clips 2`.
- [ ] Both XMLs' `Command` python path points to the `Desktop\Work\Media-Agent-main` tree.
- [ ] Both Task Scheduler tasks re-registered (visible/updated in Task Scheduler).
- [ ] Weekly task trigger confirmed Sunday 02:00 SGT; daily task trigger confirmed daily
      09:00 SGT.
- [ ] A `--dry-run` invocation of the weekly task's exact command line runs without
      `ModuleNotFoundError` and from the correct tree (no real spend).

## Blocked by

None - can start immediately.
