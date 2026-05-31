# Issue 41 — Pin the weekly 2-clip count

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/steady-state-autonomous-cadence.md` — Steady-State Autonomous Cadence (M3).
Decisions of record: `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md` (S6).

## What to build

A weekly autonomous run must produce exactly **2 clips** (one Tue, one Thu = the
$20/mo / 2-clips-per-week budget), never `clips_per_day(1) × days_per_run(7) = 7`. The
count authority is `gen_run --clips` (default 2), which caps selection via
`selected[:clips_n]` — but that invariant is currently unguarded. Pin it with a
regression test so an unattended run can never silently over-generate and blow the budget.

The test asserts the selection cap behavior directly against the selection seam with a
fake repo / patched stages: given more than 2 selectable scripts, the run selects exactly
`clips_n`. **No Kling client is constructed or called, no render runs, no spend** — per
the operator constraint that no test touches the real video-generation path.

The matching operator verification (a `gen_run --dry-run` showing exactly 2 selected
scripts slotted onto a Tuesday and a Thursday, zero spend) is recorded as part of the
enablement gate (Issue 42); this issue delivers the automated guard.

## Acceptance criteria

- [ ] A regression test asserts that with >2 selectable scripts, the run selects exactly
      `clips_n` (default 2).
- [ ] The test constructs/calls **no** Kling client and triggers no render — fakes/patches
      only, zero spend.
- [ ] The test fails if the cap is removed (e.g. selection no longer sliced by `clips_n`).
- [ ] The default `--clips` value (2) is covered so the unattended weekly command stays
      budget-bounded.

## Blocked by

None - can start immediately.
