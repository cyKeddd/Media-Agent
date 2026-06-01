# Grill record — dashboard v2 (health-first redesign + approve/reject)

**Date:** 2026-06-01
**Trigger:** User reviewed the live v1 dashboard (`http://127.0.0.1:8765/`), judged it "pretty
bad," and asked to plan v2: `/grill-with-docs → /to-prd → /to-issues → /handoff`. No coding.
**Mode:** `/grill-with-docs`. User answered each branch; took the recommendation on most and
chose layout direction explicitly.

## What v2 is for

A **health-first** local dashboard: the #1 job on open is "is the agent OK right now?" —
last generation/daily **Run** outcome, open **Alerts**, spend vs caps, queue depth — with the
review queue (now with an in-UI **Approve / Reject action**), calendar, and uploads as
supporting panels. Plus a real visual redesign ("look good").

## Terminology collision resolved

The v1 grill earmarked **"v2" = approve/reject write-path** and **"v3+" = reschedule / trigger
gen_run / edit titles / LAN**. The user used "v2" to mean a *visual redesign*. **Resolved:**
v2 now bundles the approve/reject write-path **with** the health-first redesign; the deferred
controls become **v3**. Recorded in `CONTEXT.md` → Flagged ambiguities.

## Verified code facts (this grill)

- **`runs` table** (`src/state/schema.sql:64`) records every execution: `kind`
  (`generation`/`daily`/`bootstrap`), `started_at`, `finished_at`, `success`, `summary_json`
  (per-stage counts or error string). `start_run`/`finish_run` in `repository.py:538`. v1
  surfaces **none** of this — the biggest "more useful" gap.
- **`logs/runs.md`** mirrors the table; **`logs/alerts.md`** holds structured **Alerts**
  (`gen_run_failed`, `gen_run_finished`, `loudness_warn`, `upload_quota_exceeded`,
  `recovered_slot`, `publish_at_padded`).
- **HITL gate is filesystem** (confirmed again): no `pending`/`approved` status; `daily_upload`
  trusts `output/approved/`. `config.yaml`: `human_review: true`, `paths.pending_dir`/
  `approved_dir`/`rejected_dir` configured.
- v1 stack: FastAPI + one static page; pure view-model `build_dashboard_view`; no Node/build.

## Decisions locked

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Scope = health-first redesign + in-UI approve/reject.** Reschedule/trigger/edit + LAN deferred to **v3**. | User chose redesign + write path; bundles the planned v2 write-path with the visual work. |
| D2 | **Approve/Reject moves the file only** (`pending→approved` / `pending→rejected`); no DB write. | Filesystem stays single source of truth; `daily_upload` contract unchanged. **ADR-0006.** |
| D3 | **Primary job = monitor pipeline health.** Health band on top: last gen_run + last daily_upload **Run** tiles, spend/queue tiles, recent **Alerts** feed. | User picked "monitor health"; `runs` + `alerts.md` make it real. |
| D4 | **Stack = dependency-light restyle:** FastAPI + static files, CSS design system, split vanilla JS, **no Node/build**. | Project minimal-deps ethos; localhost single-operator tool. **ADR-0005.** |
| D5 | **Auto-poll `/api/view` ~30s + manual Refresh.** | A health monitor must not show stale "healthy" while a Run has failed; cost is trivial (localhost, read-only). |
| D6 | **Action safety: confirm + server validation.** Acts only on a file currently in `pending/` (re-scan), atomic `os.replace`, Reject reversible. | Approve pushes a clip toward YouTube; prevents misclicks/stale double-actions. |
| D7 | **Approve/Reject shown only while `human_review` is on**; otherwise queue is read-only with an "autonomous mode" banner. | When review is off, `daily_upload` reads `pending/` directly — approval is a no-op; don't offer a dead button. |
| D8 | **Layout = "command-center", dark refined theme.** Health tiles top; two-column work area (review queue + preview left, calendar right); slim alerts rail; uploads collapsed at bottom. | User picked the command-center mock; matches the monitoring-console job. |

## Deferred (not v2)

- **Next-scheduled-run countdown** — needs Windows Task Scheduler query (new dep) or
  cadence-derived (can drift). → v3.
- **v3 control panel:** reschedule slots, trigger `gen_run`/dry-run, edit titles.
- **LAN exposure + token auth** (v1 + v2 stay `127.0.0.1`-only, no auth).

## Doc updates this session

- **CONTEXT.md** — added **Approve / Reject action**, **Run**, **Pipeline health**, **Alert**;
  resolved the "v2" version-numbering ambiguity in Flagged ambiguities.
- **ADR-0005** — dependency-light frontend (no SPA/build).
- **ADR-0006** — approve/reject moves files only; filesystem stays HITL source of truth.
