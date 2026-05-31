# TDD cycles — Issues 44–46 dashboard

## Cycle 1 (M1a scanner)
- RED: `test_unscheduled_pending_maps_clip_id` — module missing
- GREEN: `src/dashboard/scanner.py` with `scan_output_dirs`
- Added: slot-named slug extraction, non-MP4 ignore, approved-over-pending precedence

## Cycle 2 (M1 view-model — Review stage)
- RED: `test_pending_file_is_awaiting_review` — `_row_get` didn't read dataclass fakes
- GREEN: fixed `_row_get` + `build_dashboard_view` stage derivation
- Incremental: approved_scheduled, published, rejected, stale-path-via-scanner

## Cycle 3 (M1 calendar + uploaded + header — Issues 45–46)
- RED: calendar grouping, uploaded live/scheduled, header spend/counts
- GREEN: extended same view-model (no new module)

## Cycle 4 (M2 FastAPI smoke)
- RED: `/api/view` + `/api/video` tests
- GREEN: `src/dashboard/app.py`, static `index.html`, path-traversal guard

## Cycle 5 (Repository + CLI)
- GREEN: `list_dashboard_clips`, `count_topics_by_status`, `quota_week_total`
- GREEN: `python -m src.dashboard` entry on 127.0.0.1:8765

All 16 dashboard tests green.
