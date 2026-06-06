# TDD cycles — Issues 51–57

## Issue 51 — daily Run row
- RED: `test_build_daily_run_summary_*`, `test_run_today_writes_daily_run_row_*`
- GREEN: `build_daily_run_summary` + `run_today` start/finish bracket

## Issue 52 — retention copies
- RED: `test_finds_duplicate_copies_across_pending_and_approved`
- GREEN: basename sweep in `list_output_post_upload_candidates`

## Issue 53 — basename resolve
- RED: `test_resolver_matches_basename_when_title_slug_null`
- GREEN: `ScanResult.by_basename` + `_resolve_location` order

## Issue 54 — next-run countdown
- RED: `test_next_daily_*`, `test_view_model_includes_next_run`
- GREEN: `compute_next_runs` + view-model + app.js tiles

## Issues 55–56 — operator overrides
- RED: `test_plan_reschedule_*`, `test_plan_edit_title_*`, endpoint 409/403
- GREEN: `clip_mutation.py` + FastAPI POST handlers

## Issue 57 — directed scripts
- RED: `test_scripts_awaiting_narration_*`, `test_run_stage_b_fills_directed_*`
- GREEN: repo helpers + `run_stage_b` narration branch + contract doc
