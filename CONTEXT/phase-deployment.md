# Phase: deployment
**Project:** Media-Agent (Pivot.6)
**Status:** in-progress
**Last updated:** 2026-06-06

## Objective

Bootstrap the runtime environment, wire up Windows Task Scheduler for fire-and-forget operation, and live-verify each phase before marking it complete. Deployment is the final gate before a phase is considered done.

## Key Decisions

- **Windows Task Scheduler** — not cron. `scripts/weekly_run.xml` (Sunday 02:00 SGT → gen_run.py), `scripts/daily_upload.xml` (daily 09:00 SGT → daily_upload.py). Both run under user account.
- **Fire-and-forget operational model:** No daemon, no queue. Scheduler invokes scripts; scripts exit when done. Run lock (`data/.gen_run.lock`) prevents concurrent executions.
- **`bootstrap.py` as health check:** `python -m src.bootstrap --check` verifies Python, ffmpeg+NVENC, CUDA, Ollama+qwen2.5:3b, YouTube OAuth. Must pass before any live run. `--init-db` creates schema. `--smoke` runs end-to-end pipeline test.
- **Human review gate (first 2 weeks):** `human_review: true` in config. `daily_upload.py` only uploads clips in `output/approved/`. User drags MP4s from `output/pending/` → `output/approved/` manually.
- **Orphan-marker fence:** `uploader/orphan_marker.py` writes a marker file BEFORE `videos.insert` call. On startup, `reconcile_orphans()` detects mid-upload crashes. Prevents double-upload.
- **Run lock:** msvcrt advisory lock (`src/observability/run_lock.py`). Windows-native.
- **Observability:** `logs/agent.log` (loguru, rotated daily, 30-day retention), `logs/alerts.md` (append-only alert table), `logs/runs.md` (per-run summary table). No Discord/webhooks.
- **OAuth flow:** One-time interactive setup via `scripts/oauth_first_run.py`. Token stored at `data/oauth_token.json` (gitignored). Refresh handled automatically by YouTube client.
- **Secrets:** `data/client_secret.json` (Google OAuth), `data/oauth_token.json` (refresh token), `.env` (OPENROUTER_API_KEY). All gitignored. `.env.example` committed.
- **Quota ceiling:** `youtube_quota_ceiling_units: 9000` (conservative below 10,000 free tier). `videos_insert_unit_cost: 1600`.
- **NVENC requirement:** ffmpeg must be compiled with `--enable-nvenc`. CUDA 12.x required. Verified in bootstrap `--check`.
- **Hermes director (ADR-0008):** Nous Hermes Agent at `%LOCALAPPDATA%\hermes\` authors **Directed scripts** in `data/state.db` via `execute_code`. Runs **before** Sunday `gen_run`; does **not** take `data/.weekly_run.lock`. Does **not** run `gen_run` — operator or Task Scheduler does. Contract: `docs/hermes-director-contract.md`.

---

## Operational Pre-Flight Checklist for `daily_upload.py`

Before any real (non-`--dry-run`) invocation:

- [ ] `output/orphans/` is empty (or all markers reconciled).
- [ ] `data/oauth_token.json` exists and is < ~50 days old.
- [ ] No other process holds `data/.weekly_run.lock`.
- [ ] `quota_ledger` has ≥1600 units headroom per planned insert.
- [ ] The MP4 in `output/approved/` basename matches `output_path` in its `clips` row.
- [ ] Run `python -m src.daily_upload --dry-run` first; eyeball the full upload JSON; confirm `containsSyntheticMedia=true`, `madeForKids=false`, description footer is present, and there is no source/channel attribution.

---

## Accomplishments

- [2026-05-06] **Phase 5 live-verified:** First real YouTube upload via `uploader/runner.py`. OAuth flow confirmed.
- [2026-05-06] **Phase 6 live-verified:** `slot_planner` + `daily_upload.py` — publish_at scheduling confirmed.
- [2026-05-07] **Phase 5/6 re-verified:** Second upload successful. Orphan-marker fence confirmed working.
- [2026-05-09] **Phase 7 live-verified:** Run lock, retention kill-switch, tenacity retry, UTF-8 fixes — all confirmed on live run.
- [2026-05-09] **Phase 4.5 live-verified:** policy_gate + quality_screen gates exercised on real rendered clip.
- [2026-05-21] **Slice 2 spike deployed:** 8 Kling shots generated via `scripts/generate_clip.py`. Auth fix pushed (`fcf2385`).
- [2026-05-22] **Slice 8 committed:** `src/gen_run.py` commit `82ce0d1`. Task Scheduler XML points to this.
- [2026-05-24] **Slice 10 live upload:** `9lpL8kuLX08` (Corti candidate).
- [2026-05-28] **Post-ADR-0004 sample upload:** clip `092b3504` → YouTube `qRdVYO1Tmfw` via `src.uploader --clip-id`; scheduled `publishAt=2026-06-02T01:00:00Z` (09:00 SGT). Operator HITL approve path exercised.
- [2026-05-31] **Issue 40 scheduler fix:** XMLs repointed to Desktop tree + `src.gen_run --clips 2`; `MediaAgentWeekly` + `MediaAgentDailyUpload` re-registered and Enabled.
- [2026-06-06] **Hermes director first run:** Directed script `ebba0850-7d30-4ee5-aee6-8f50ffc6d18a` (topic 130, Gemini Omni) inserted; topic claimed. `gen_run` consume pending operator PowerShell run.

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Weekly scheduler XML | `scripts/weekly_run.xml` | Sunday 02:00 SGT — `src.gen_run --clips 2` (Desktop tree) |
| Daily scheduler XML | `scripts/daily_upload.xml` | Daily 09:00 SGT — calls daily_upload.py |
| OAuth setup script | `scripts/oauth_first_run.py` | One-time interactive auth |
| Bootstrap | `src/bootstrap.py` | --check, --init-db, --smoke |
| Run lock | `src/observability/run_lock.py` | msvcrt Windows advisory lock |
| Alerts log | `logs/alerts.md` | Append-only; check after every live run |
| Runs log | `logs/runs.md` | Per-run summary table |
| Orphan markers dir | `output/orphans/` | Fence files; cleaned up after verify |
| Secrets template | `.env.example` | OPENROUTER_API_KEY, etc. |
| Setup guide | `README.md` | Full one-time setup + scheduling steps |

## Sessions

- Phase 5/6 live verification (2026-05-06 / 2026-05-07)
- Phase 7 hardening live run (2026-05-09)
- Slice 2 spike deploy (2026-05-21)
- Slice 8/9 commit + push (2026-05-22)
- [issues-39-42-tdd](.sessions/2026-05-31__issues-39-42-tdd/handoff.md) — 2026-05-31
- [hermes-director-first-directed-script](../.sessions/2026-06-06__hermes-director-first-directed-script/handoff.md) — 2026-06-06

## Open Items

- **Issue 58 E2E** — Run `python -m src.gen_run --clips 1` to consume directed script `ebba0850-…`; then schedule Hermes cron (Saturday SGT).
- **[BLOCKING for Slice 10]** Apply migration: `python scripts/migrate_pivot_6_3.py --dry-run` then live. Back up `data/state.db` first.
- **[BLOCKING for Slice 10]** Assemble MP4 from 8 spike shots in `data/ai_gen_shots/spike_2026-05-21/` → `output/pending/`.
- ~~Task Scheduler XMLs not yet re-registered~~ — **fixed 2026-05-31** (Issue 40).
- Issue 29 ship gate **Thu 2026-06-04** on `NPFJiqmd4ro`; stability gate ~2026-06-06.
- First unattended scheduler weekly run: **Sun 2026-06-07 02:00 SGT** (after ship gate).
