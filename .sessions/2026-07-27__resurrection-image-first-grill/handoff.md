# Handoff — Resurrection + image-first polish (grill → PRD → Issues 59–70)

**Date:** 2026-07-27
**Session type:** `/part1` — planning only, **no application code written**
**Tracker:** GitHub `Media-Agent/Media-Agent`, label `Agent Ready` → syncs to Linear team **MED**

---

## The headline

**The channel is not underperforming — it has been dead since 2026-06-02, silently.**

The session opened on a request to "polish" an allegedly working pipeline. Probing `state.db`,
`logs/`, and Task Scheduler showed it has produced nothing for eight weeks.

| Signal | Value |
|---|---|
| Last OpenRouter spend | **2026-05-31** (4 shots × 63¢) |
| Last upload | `NPFJiqmd4ro`, published 2026-06-02 |
| Every `generation` run since | `generate_clips=0` |
| Runs 2026-06-22, 2026-07-18 | started, **never finished** (`finished_at IS NULL`) |
| `MediaAgentWeekly` last result | `3221225786` (`0xC000013A`), fired 2026-07-26 02:00 |
| `daily_upload` | fires fine, always `no_candidates` |
| Backlog | 12 `unscripted` topics, 34 `pending` scripts, `output/pending/` empty |

### Root causes (both certain)

1. **`src/gen_run.py` and `src/daily_upload.py` never call `load_dotenv`.** Only ad-hoc
   `scripts/*.py` do. Under Task Scheduler `OPENROUTER_API_KEY` is unset →
   `src/gen_run.py:305` raises `RuntimeError("OPENROUTER_API_KEY required for ai_video shots")`.
2. **The `OPENROUTER_API_KEY` in `.env` is 13 characters** — a placeholder. A real key is ~73
   (`sk-or-v1-` + 64 hex). Loading `.env` alone would not have fixed it.

Compounding both: **nothing alerted.** `logs/alerts.md` has not been written since 2026-06-07.
A hard-killed run leaves `finished_at IS NULL` forever and emits no signal, so an eight-week
outage was indistinguishable from a quiet week.

### Also found

- **Budget guardrail is 7× the budget.** `daily_spend_cents_ceiling: 500` = $5/day = $35/week.
  **No weekly cap exists in the code at all.** `per_clip_cost_cents_max` drifted (config `300`,
  `progress.md` `250`).
- **`quota_usage` has no `used_at` column** — it is `recorded_at` plus a separate `date`. Any
  window query must use the real schema.

### Investigated and dismissed

- **The stale `data/.weekly_run.lock` (0 bytes, 2026-06-01) is NOT a blocker.** `acquire_run_lock`
  uses an advisory `msvcrt` byte lock that the OS releases on process death; the leftover file is
  intentional (`run_lock.py` docstring). Nearly filed a bogus issue here — do not re-litigate.

---

## Locked decisions

| # | Decision |
|---|---|
| D1 | Budget **$8/week**, all-in (video + stills) — raised from $5 by the user |
| D2 | Cadence **5 Clips/week** (~$4.40), ~45% headroom for retries |
| D3 | Video model **`bytedance/seedance-2.0-fast`** ($0.0538/s), image-to-video. User chose to start here and revisit rather than run a bake-off |
| D4 | Still model **`google/gemini-3.1-flash-image`** (Nano Banana 2, ≈$0.004/still) |
| D5 | **Licensed source first** for named real entities; **Generated still** only on a miss or for shots naming no real entity |
| D6 | **Clip stays ~16 s** (4 Shots × ~4 s) |
| D7 | `human_review` stays **true** |
| D8 | **Hermes director** optional; qwen path is the guaranteed fallback |
| D9 | Freshness from **free feeds** — Techmeme, HN promoted to a topic *source*, AI-scoped Google News RSS |
| D10 | Issues written to **GitHub only**; sync mirrors into Linear MED. One write surface, no duplicates |

**X/Twitter ingestion was evaluated and deferred by the user.** Official X read access is
~$17/week at this volume against an $8/week total budget (free read tier discontinued; pay-per-use
$0.005/read). Third-party resellers (twitterapi.io ≈$0.15/1k tweets) are ~40× cheaper but ToS-grey
and fragile. Freshness is instead addressed by D9.

### Architecture decision

**[ADR-0009](../../docs/adr/0009-image-first-shot-generation.md) — every Shot is generated
image-first, then animated image-to-video.** A still costs ~$0.004; the video second it conditions
costs ~$0.054, so a still is ~50× cheaper than the frame it controls. Cost per Clip falls
**~$2.02 → ~$0.88**, roughly tripling affordable output at the same spend, while style coherence
and factual grounding both improve. Text-to-video becomes the last-resort fallback; Ken Burns
becomes the fallback motion path.

---

## Invariants (binding — part2 red-teams against these)

Full text in the PRD. Summary:

- **INV-1** Rolling 7-day OpenRouter spend ≤ **800¢**; refuse before the call, never a silent skip
- **INV-2** Cumulative spend per `script_id` incl. retries ≤ **150¢**
- **INV-3** One Generated still ≤ **5¢**; all stills per Clip ≤ **20¢**
- **INV-4** No `runs` row stays `finished_at IS NULL`; swept to `success=0` after **90 min**
- **INV-5** No Clip rendered in **7 days** → `liveness_stalled` alert
- **INV-6** Both entry points load `.env`; `bootstrap --check` fails unless the key matches
  `^sk-or-v1-[0-9a-f]{64}$`; key never logged
- **INV-7** Licensed source MUST win when it resolves; Generated still only on a miss
- **INV-8** No shot prompt (video *or* still) names/depicts an identifiable living person
- **INV-9** AI disclosure unchanged (`containsSyntheticMedia=true`)
- **INV-10** Providers behind `Provider` / `StillProvider`; swapping is config-only
- **INV-11** `gen_run --clips 5` ≤ **90 min**; one Shot's submit+poll ≤ **10 min**
- **INV-12** Degradation ladder per dependency. **Notably: OpenRouter 401/403 aborts the run
  immediately — no retry loop.** That is the failure that cost eight weeks
- **INV-13** Dashboard binds `127.0.0.1`; `.env` stays gitignored

---

## Issues 59–70

| # | Title | WS | Pri | Blocked by |
|---|---|---|---|---|
| 59 | Entry points load `.env`; `bootstrap --check` validates key shape | WS1 | 1 | — |
| 60 | Guarantee terminal run state; sweep abandoned runs | WS1 | 1 | 59 |
| 61 | Liveness alert + fail-fast on OpenRouter auth errors | WS1 | 1 | 59, 60 |
| 62 | Weekly spend ceiling (800¢) + reconcile per-clip cap | WS1 | 1 | (land after 60) |
| 63 | `Provider` ABC accepts a first-frame image | WS2 | 2 | — |
| 64 | Nano Banana 2 still provider | WS2 | 2 | 63, 62 |
| 65 | Seedance 2.0 Fast image-to-video provider | WS2 | 2 | 63 |
| 66 | Image-first shot routing ladder | WS2 | 2 | 64, 65 |
| 67 | Switch runtime defaults to image-first + Seedance | WS2 | 2 | 66 |
| 68 | Subtitle and typography restyle | WS3 | 3 | — |
| 69 | Freshness: Techmeme, HN as source, Google News | WS4 | 3 | — |
| 70 | Live resurrection run + spend reconciliation (HITL) | WS5 | 1 | 59–62, 67 |

Specs: `docs/issues/59-*.md` … `docs/issues/70-*.md`. Each carries a runnable
**Verification-command**. Issues 63, 68, 69 are independent and parallel-safe.

---

## State of the tracker

- **GitHub issue #1 = Issue 59**, label `Agent Ready`, confirmed synced to Linear MED by the user.
  <https://github.com/Media-Agent/Media-Agent/issues/1>
- **Issues 60–70 are NOT yet filed in GitHub.** `gh issue create` was blocked by the Claude Code
  permission classifier after #59 succeeded. The specs exist on disk and are ready to file; this
  needs a Bash permission rule or manual creation.
- **Repo note:** `cyKeddd/Media-Agent` redirects to **`Media-Agent/Media-Agent`** — the repo lives
  in the `Media-Agent` org. Use the org path.
- **Linear MCP note:** the connected Linear token is scoped to a *different* workspace (only team
  "Windows Game Optimizer" is visible; querying `MED` returns empty). Direct Linear writes are not
  possible until it is re-authed to the `media-agent` workspace. Not a blocker — sync covers it.

---

## Immediate next action

1. **File Issues 60–70** in `Media-Agent/Media-Agent` with the `Agent Ready` label, bodies from
   `docs/issues/`. Blocked on a permission rule for `gh issue create`.
2. **Put a real `OPENROUTER_API_KEY` in `.env`** — a funded key matching
   `^sk-or-v1-[0-9a-f]{64}$`. Issue 70 cannot run without it, and Issue 59's check is designed to
   fail on the current placeholder.
3. **Start part2 on Issue 59** — it is the only unblocked P1 in WS1 and everything else waits on it.

## Notes for the next agent

- **Do not trust "the pipeline works."** It has not rendered a Clip since 2026-06-02. Re-verify
  against `quota_usage` and `output/pending/`, not against the `runs.success` flag — every dead run
  reported `success=true` with `generate_clips=0`.
- The two abandoned `runs` rows (2026-06-22, 2026-07-18) are **left in place deliberately** as live
  fixtures for Issue 60's finalizer. Do not clean them by hand.
- Only **Issue 70** has spend authority. Everything else must be tested against fakes.
