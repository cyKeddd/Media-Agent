# Grill record — steady-state autonomy path

**Date:** 2026-05-31
**Trigger:** First hybrid clip `NPFJiqmd4ro` uploaded (publish moved to Thu 2026-06-04);
Issues 35–38 done. User asked to grill "what's next" before a PRD, then run
`/to-prd → /to-issues → /handoff`. New ask raised: a web review/calendar dashboard.
**Mode:** `/grill-with-docs`. User delegated most calls ("do the recommended").

## North star (unchanged)

> The autonomous loop (weekly `gen_run` + daily `daily_upload`) ships **Hybrid clips**
> on the Tue/Thu cadence, with the first hybrid Short live-verified through the two-gate.

This task = make that loop run **unattended on Task Scheduler** after the first-hybrid
two-gate, with the off-niche leak closed, the budget topped up, and a defined trigger to
drop `human_review`.

## Verified facts (this grill)

- **Off-niche clip root-caused to a pre-gate backlog, not the classifier.** The
  reverse-aging clip (script `1ec5cbc1`) came from **topic #69**, fetched **2026-05-20**
  off DeepMind's feed (AI "Co-Scientist" applied to biology, significance 9.0) — a week
  **before** the ADR-0004 ingest relevance gate shipped (2026-05-27). It was never gated.
  **112 of 117 `unscripted` topics are pre-gate;** the scripter draws the highest-scored
  `unscripted` topic, so the next autonomous run keeps pulling un-gated topics. The
  new-ingest gate itself works well (agent.log shows ~10 correct off-niche rejections/run).
- **Scheduler XMLs are stale.** `weekly_run.xml` runs `-m src.weekly_run` (renamed to
  `gen_run`); both `weekly_run.xml` and `daily_upload.xml` point their `.venv` python at
  `C:\Users\cryptix\Documents\Media-Agent-main` — a different repo copy than the live
  `C:\Users\cryptix\Desktop\Work\Media-Agent-main`. The `gen_run_failed`
  `ModuleNotFoundError` entries in `logs/alerts.md` corroborate.
- **Config grounded:** `clips_per_day: 1`, `days_per_run: 7`, `upload_weekdays: [tue,thu]`,
  `human_review: true`, `per_clip_cost_cents_max: 250`, `daily_spend_cents_ceiling: 500`,
  `pitch: "+0Hz"`. Open question: does a weekly run yield 2 clips (weekday allocator) or 7
  (`clips_per_day×days_per_run`)? Must verify — budget guard.
- **Balance:** ~63¢ on OpenRouter; insufficient for another clip (~$2 floor).

## Decisions locked

| # | Decision | Rationale |
|---|---|---|
| S1 | **PRD/issues target = steady-state path.** Dashboard = explicit next-up follow-on, not built now. | User scoping; dashboard is a separate build + grill. |
| S2 | **Slot dedup:** hybrid `NPFJiqmd4ro` → **Thu 2026-06-04**; sample `qRdVYO1Tmfw` stays **Tue 2026-06-02**. | Clean Tue+Thu week; two-gate subject stands alone. |
| S3 | **Off-niche fix = backfill-gate the 112-topic legacy `unscripted` backlog** with the existing on-niche classifier; keep on-niche legacy items. Retires deferred G3 prompt retune. Scripter-framing drift = deferred follow-up only. | Root cause is un-gated legacy topics, not the prompt. |
| S4 | **Enable-scheduler trigger = ship gate (T+1h Thu 06-04) + prereqs** (top-up, backfill, XML re-register). Stability monitored in parallel; `human_review` stays ON. | ADR-0001: ship gate unblocks forward work; review contains risk. |
| S5 | **`human_review` true→false trigger = evidence-based + calendar floor:** stability gate passed AND ≥2 clean scheduler-driven cycles AND ≥2 weeks since 06-04. | Confidence is in the *autonomous* path, which must run clean unattended first. |
| S6 | **Fix scheduler XMLs:** `src.weekly_run`→`src.gen_run`; repoint `Documents\`→`Desktop\Work\`; verify 2-clip weekly count. | Confirmed defects; each breaks or over-spends an unattended run. |
| S7 | **OpenRouter top-up = $20** (~8 clips/one month); `daily_spend_cents_ceiling: 500` unchanged. | Aligns to $20/mo cadence budget. |

## Doc updates this session

- **phase-planning.md** — 7 locked decisions appended (2026-05-31 block).
- **CONTEXT.md glossary** — intentionally unchanged (mechanism/remediation decisions, not
  new durable domain terms; consistent with the 2026-05-30 grill's choice).
- **No new ADR** — sequencing/remediation only; ADR-0001 (two-gate) + ADR-0004 (niche
  gate) already cover the durable architecture.

## Out of scope (deferred)

Web review/calendar dashboard (next-up, separate grill/PRD); scripter content-quality grill
+ framing-drift fix; niche-classifier prompt retune (now retired as the wrong fix); Phase 8
stretch; quota-increase audit; CUDA cuBLAS PATH; Kokoro install.
