# TDD cycles — Issues 39–41

## Issue 39 — backfill_unscripted_topics

| Cycle | Test | Result |
|---|---|---|
| RED | `tests/test_topic_ingest_backfill.py` (6 tests) — module missing | 6 FAILED |
| GREEN | `src/topic_ingest/backfill/` + `mark_topic_rejected_off_niche` | 6 PASSED |

## Issue 41 — clips_n cap

| Cycle | Test | Result |
|---|---|---|
| RED→GREEN | `test_clips_n_caps_selection_at_default_two` — assert `scripter_c.count==2` | PASSED (cap already in `gen_run`) |

## Issue 40 / 42

Config + operator steps — no TDD cycles (XML fix, schtasks re-register, live backfill, dry-run evidence).
