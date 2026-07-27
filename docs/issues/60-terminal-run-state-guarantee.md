# Issue 60 — Guarantee terminal run state; sweep abandoned runs

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 1 (Urgent — an eight-week outage was invisible because dead runs leave no signal)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS1.

## What to build

Make it impossible for a **Run** to die silently.

`src/gen_run.py` writes its `runs` row at line 433 (`repo.start_run(kind="generation")`) and
finalizes at 567 (success) or 580 (failure). Both finalizers live inside the try/except, so a
*hard* process death — `MediaAgentWeekly` last exited `3221225786` (`0xC000013A`, abnormal
termination) — leaves the row `finished_at IS NULL` forever. Two such rows exist right now:
`generation` runs started 2026-06-22 09:42:34 and 2026-07-18 08:48:46.

Scope:

- On startup, **both** entry points sweep `runs` for rows where `finished_at IS NULL` and
  `started_at` is older than `run_hang_minutes` (new config key, default **90**). Each is finalized
  `success=0` with summary `{"message": "abandoned", "started_at": ...}` and an appended alert of
  kind `run_abandoned`.
- The sweep runs **after** the run lock is acquired, so a genuinely in-flight run held by another
  process is never swept.
- The sweep is idempotent — running it twice finalizes nothing the second time.
- A run younger than the threshold is left alone.

The 90-minute threshold is deliberately the same number as INV-11's latency budget: a `gen_run`
that has not finished in 90 minutes is by definition over budget, so treating it as abandoned is
consistent rather than arbitrary.

## Invariants

- **INV-4** — No `runs` row may remain `finished_at IS NULL` once no process holds it. Any run
  whose `started_at` is older than 90 minutes with no `finished_at` is swept to `success=0` at the
  next entry-point start, with an alert.
- **INV-11** — The 90-minute threshold matches the `gen_run --clips 5` wall-clock budget.

## Acceptance criteria

- [ ] New config key `run_hang_minutes`, default 90, surfaced through the Pydantic config.
- [ ] A `runs` row with `finished_at IS NULL` and `started_at` older than the threshold is
      finalized `success=0`, summary message `abandoned`, and produces a `run_abandoned` alert.
- [ ] A row younger than the threshold is untouched.
- [ ] A row already finalized is untouched (idempotent).
- [ ] The sweep happens after run-lock acquisition, proven by a test in which the lock is held.
- [ ] Both `gen_run` and `daily_upload` perform the sweep.
- [ ] The two real abandoned rows (2026-06-22, 2026-07-18) are finalized on the first live run —
      note this in the ticket evidence rather than mutating the DB by hand.

## Blocked by

- Issue 59 (entry points must load `.env` before their startup path is meaningfully exercised).

## Verification-command

```
pytest tests/test_run_finalizer.py -q
```
