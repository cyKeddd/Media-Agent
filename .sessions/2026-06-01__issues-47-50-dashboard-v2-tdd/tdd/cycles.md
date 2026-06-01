# TDD cycles — Issues 47–50 dashboard v2

## Cycle 1 (M2 run reader)
- RED: `test_latest_run_per_kind_*` — module missing
- GREEN: `src/dashboard/run_reader.py` + `latest_run_per_kind`

## Cycle 2 (M1 health rollup)
- RED: `test_overall_status_*` — `PipelineStatus` / `health` missing
- GREEN: extended `view_model.py` (`HealthView`, `derive_overall_status`, `view_to_json`)

## Cycle 3 (M3 alerts parser)
- RED: `test_parse_alerts_*`
- GREEN: `src/dashboard/alerts_parser.py`; wired in `app.py` → `recent_alerts`

## Cycle 4 (M4 review action)
- RED: approve/reject/unreject/refuse tests
- GREEN: `src/dashboard/review_action.py` + POST endpoints in `app.py`

## Cycle 5 (M5 FastAPI + frontend)
- GREEN: extended `test_dashboard_app.py` (health shape, POST approve, human_review gate)
- GREEN: `static/styles.css`, `static/app.js`, command-center `index.html`

31 dashboard tests green.
