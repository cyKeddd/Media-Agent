# TDD cycles — Issue 43

| Cycle | Test | Result |
|---|---|---|
| RED | `test_script_spend_total_sums_attributed_charges` | FAILED (no script_id on quota_record) |
| GREEN | schema + repository attribution | PASSED |
| RED | `test_generate_shots_refuses_charge_pushing_lifetime_over_cap` | FAILED |
| GREEN | cumulative pre-submit check in `generate_shots` | PASSED |
| RED | `test_generate_shots_reuses_succeeded_jobs_without_billing` | FAILED (FK + copy) |
| GREEN | `upsert_generation_job` + same-path reuse skip | PASSED |
| RED | `test_retry_after_post_billing_failure_totals_126_not_252` | FAILED |
| GREEN | persistent `data/ai_gen/{script_id}/` + retry reuse | PASSED |
