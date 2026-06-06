# Issue 51 — daily_upload writes a daily Run row (dashboard daily tile populates)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS1. Decisions of record:
`CONTEXT/CONTEXT.md` (glossary: **Run**, **Pipeline health**).

## What to build

`daily_upload` records a SQLite **Run** row (`kind='daily'`) so the dashboard's daily health
tile reflects reality instead of "Not yet run". Today `daily_upload` only appends to
`logs/runs.md`; `gen_run` is the only writer of the `runs` table. Mirror `gen_run`'s pattern.

End-to-end behavior:

- A pure `build_daily_run_summary(results) -> dict` maps upload outcomes to the JSON shape the
  dashboard already reads: `{"uploaded": <count of successful inserts>}` on a normal Run,
  `{"message": "no_candidates"}` when nothing was due, `{"error": "<reason>"}` on an
  orphan-reconcile abort or an unexpected crash. (Shape dictated by
  `view_model._run_success_detail` — `uploaded`/`message` — and `run_reader._parse_summary` —
  top-level `error` → Failed tile.)
- In the daily run path: when **not** `--dry-run`, `start_run("daily")` once at the top;
  `finish_run(run_id, success, summary_json)` on **every** exit (orphan abort → failed;
  no-candidates → success; normal completion → success; quota-break still finalizes). Wrap the
  body so an unexpected exception finalizes the row `success=False` with `{"error": ...}` then
  re-raises — exactly as `gen_run` does.
- `--dry-run` writes **no** `runs` row (so a manual dry-run never masquerades as the latest real
  daily Run on the dashboard). The existing `runs.md` append is kept for both modes.
- Correct the stale `runs.kind` schema comment from `weekly|daily|bootstrap` to `generation|daily`.

## Acceptance criteria

- [ ] `build_daily_run_summary` returns `{"uploaded": N}` for N successful uploads,
      `{"message": "no_candidates"}` for an empty window, `{"error": ...}` for orphan-abort.
- [ ] A real (non-dry-run) daily Run writes one `runs` row with `kind='daily'`, correct
      `success`, and `summary_json` matching the builder, on each exit path (orphan abort,
      no-candidates, normal, quota-break, exception).
- [ ] `--dry-run` writes **no** `runs` row; `runs.md` still gets its line in both modes.
- [ ] An unexpected exception finalizes the row `success=False` with an `error` summary, then
      re-raises (no orphaned in-progress row on crash).
- [ ] The dashboard renders the daily tile from a written row: `uploaded=N` / `no_candidates` /
      Failed (with error) / In progress (finished_at null) — no dashboard code change required.
- [ ] `runs.kind` schema comment reads `generation|daily`.
- [ ] Tests: unit over `build_daily_run_summary` permutations; integration that the run path
      writes/does-not-write the row per mode and exit; a render assertion via
      `run_reader`/`view_model` for each tile state. No live YouTube/OAuth.

## Blocked by

- None — can start immediately.
