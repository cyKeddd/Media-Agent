# PRD — Resurrection + image-first polish

**Status:** ready-for-agent
**Date:** 2026-07-27
**Issues:** 59–70
**Decisions of record:** [ADR-0009](../adr/0009-image-first-shot-generation.md) (image-first
shots), [ADR-0003](../adr/0003-licensed-only-image-sourcing-for-autonomous-ships.md) (licensed
sourcing, upheld), [ADR-0008](../adr/0008-hermes-director-authors-scripts-rows.md) (Hermes
director, unchanged).

## Problem

The channel is dead and has been for eight weeks, silently.

Evidence gathered 2026-07-27 from `data/state.db`, `logs/`, and Task Scheduler:

| Signal | Value |
|---|---|
| Last OpenRouter spend | **2026-05-31** (4 shots × 63¢) — zero video spend since |
| Last upload | `NPFJiqmd4ro`, published 2026-06-02 |
| Every `generation` run since | `generate_clips=0` |
| Runs 2026-06-22 and 2026-07-18 | started, **never finished** (`finished_at IS NULL`) |
| `MediaAgentWeekly` last result | `3221225786` (`0xC000013A`), fired 2026-07-26 02:00 |
| `daily_upload` | fires correctly, always `no_candidates` |
| Backlog | 12 `unscripted` topics, 34 `pending` scripts, `output/pending/` empty |

Two stacked root causes are certain:

1. **`src/gen_run.py` and `src/daily_upload.py` never call `load_dotenv`.** Only ad-hoc
   `scripts/*.py` do. Under Task Scheduler `OPENROUTER_API_KEY` is unset, so
   `gen_run.py:305` raises `RuntimeError("OPENROUTER_API_KEY required for ai_video shots")`.
2. **The `OPENROUTER_API_KEY` value in `.env` is 13 characters** — a placeholder. A real
   OpenRouter key is ~73 (`sk-or-v1-` + 64 hex). Loading `.env` alone would not fix it.

Compounding both: **nothing alerted.** `logs/alerts.md` has not been written since 2026-06-07.
A run that dies hard leaves a `runs` row with `finished_at IS NULL` forever and emits no signal,
so an eight-week outage looked identical to a healthy idle week.

Separately, the budget guardrail does not match the stated budget: `daily_spend_cents_ceiling: 500`
is **$5/day = $35/week**, seven times the intended spend, and **no weekly cap exists in the code
at all.** `per_clip_cost_cents_max` also drifted (config says `300`, `progress.md` says `250`).

Finally, output quality is limited by the generation architecture itself — text-to-video re-rolls
composition on every retry, style drifts across the four **Shots** of a **Clip**, and a
**Licensed source** miss degrades the **Shot** to an unrelated generic clip.

## Goals

1. **Get the channel producing again**, and make a future stall impossible to miss.
2. **Make spend match the stated budget** — $8/week, enforced weekly, not just daily.
3. **Raise visual quality** by moving to image-first generation (ADR-0009), within that budget.
4. **Improve topic freshness** without paid X/Twitter access.

## Non-goals

- X/Twitter ingestion. Evaluated and deferred by the user: official X read access is ~$17/week at
  this volume against an $8/week total budget, and third-party resellers are ToS-grey and fragile.
- Any change to the upload, disclosure, slot-planning, or dashboard write paths.
- Flipping `human_review` off. It stays **on**.
- A model bake-off. The user chose to start on `bytedance/seedance-2.0-fast` and revisit later.

## Locked decisions

| # | Decision |
|---|---|
| D1 | Budget rises to **$8/week**, all-in (video + stills). |
| D2 | Cadence **5 Clips/week** (~$4.40), leaving ~45% headroom for retries. |
| D3 | Video model **`bytedance/seedance-2.0-fast`** ($0.0538/s), image-to-video. Revisit later. |
| D4 | Still model **`google/gemini-3.1-flash-image`** (Nano Banana 2, ≈$0.004/still). |
| D5 | **Licensed source first** for any named real entity; **Generated still** only on a miss or for shots naming no real entity (ADR-0009, INV-7). |
| D6 | **Clip stays ~16 s** — 4 **Shots** × ~4 s. |
| D7 | `human_review` stays **true**. |
| D8 | **Hermes director** stays optional; the qwen path is the guaranteed fallback. |
| D9 | Freshness comes from **free feeds** — Techmeme, Hacker News promoted to a topic *source*, and AI-scoped Google News RSS queries. |
| D10 | Issues are written to **GitHub only** (`cyKeddd/Media-Agent`, label `Agent Ready`); GitHub→Linear sync mirrors them into team **MED**. One write surface, no duplicates. |

## Invariants (acceptance constraints)

These are binding. Every issue that touches one restates it in its acceptance criteria.

### Spend

- **INV-1 — Weekly ceiling.** Rolling 7-day OpenRouter spend ≤ **800¢**. `gen_run` refuses to issue
  a billable call that would cross it. A refusal is explicit: alert `spend_cap_reached` plus a
  `capped` run summary — never a silent skip.
- **INV-2 — Per-clip ceiling.** Cumulative spend attributed to one `script_id`, *including retries
  and regenerated shots*, ≤ **150¢**.
- **INV-3 — Per-still ceiling.** One **Generated still** ≤ **5¢**; all stills for one **Clip** ≤
  **20¢**.

### Liveness and failure

- **INV-4 — Terminal run state.** No `runs` row may remain `finished_at IS NULL` once no process
  holds it. Any run whose `started_at` is older than **90 minutes** with no `finished_at` is swept
  to `success=0` at the next entry-point start, with an alert.
- **INV-5 — Liveness.** If no **Clip** has been rendered in **7 days**, an alert of kind
  `liveness_stalled` is appended on the next run of either entry point.
- **INV-6 — Secret loading and shape.** Both entry points load `.env` before config resolution.
  `bootstrap --check` **fails** when `OPENROUTER_API_KEY` does not match
  `^sk-or-v1-[0-9a-f]{64}$`. The key never appears in a log, alert, or committed file.
- **INV-11 — Latency budget.** `gen_run --clips 5` completes within **90 minutes** wall-clock on
  the target hardware (aligned with INV-4's sweep threshold). One **Shot**'s submit+poll ≤ **10
  minutes** (the existing `timeout_s=600`).
- **INV-12 — Degradation ladder.** Per external dependency:

  | Dependency | Condition | Behaviour |
  |---|---|---|
  | OpenRouter | 5xx / timeout | tenacity retry ×3 with backoff → **Shot** fails → **Clip** abandoned, incurred spend recorded, alert |
  | OpenRouter | **401 / 403** | **abort the run immediately**, alert `auth_failed`, no retry loop — this is the failure that cost eight weeks |
  | OpenRouter | would cross weekly cap | refuse **before** the call (INV-1) |
  | Licensed source | miss | **Generated still** (INV-7) |
  | Still model | failure | fall back to text-to-video **Shot** |
  | Edge TTS | throttle | tenacity retry → `pyttsx3` offline fallback (existing) |
  | Ollama | down | abort at scripter, alert, **zero spend** |
  | YouTube | quota | existing ledger abort (unchanged) |

### Content integrity

- **INV-7 — Factual imagery.** A **Shot** whose entity names a real product, company, or logo MUST
  use a **Licensed source** still when one resolves. A **Generated still** is permitted only on a
  licensed miss, or when the **Shot** names no real entity.
- **INV-8 — No living individuals.** No shot prompt — video *or* still — may name or depict an
  identifiable living person. Narration may state facts about real people; prompts may not name
  them. This now binds the still generator too.
- **INV-9 — AI disclosure.** Unchanged. Every `content_kind='ai_generated'` upload sets
  `status.containsSyntheticMedia=true` and carries the "Made with AI" footer. **Generated stills**
  do not alter this.

### Structure

- **INV-10 — Provider swap.** Every video generator implements `Provider`; every still generator
  implements `StillProvider`. Swapping either is a **config-only** change with no downstream
  pipeline edit.
- **INV-13 — Security boundary.** The dashboard binds `127.0.0.1` only. `.env` stays gitignored.

## Workstreams

**WS1 — Resurrection (P1, blocks everything).** Issues 59–62.
Load `.env`, validate key shape, guarantee terminal run state, add liveness alerts, enforce the
weekly cap. After WS1 the pipeline either runs or says loudly why it didn't.

**WS2 — Image-first generation (P2).** Issues 63–67.
Extend `Provider` with first-frame conditioning, add the Nano Banana 2 **Still provider** and the
Seedance image-to-video provider, implement the ADR-0009 routing ladder, switch config defaults.

**WS3 — Presentation polish (P3).** Issue 68.
Subtitle and typography restyle.

**WS4 — Freshness (P3).** Issue 69.
Techmeme, HN-as-source, Google News keyword feeds.

**WS5 — Live verification (P1, HITL).** Issue 70.
A real `gen_run` producing a reviewable MP4 with reconciled spend. This is the gate that proves
the resurrection actually worked.

## Success criteria

- A scheduler-driven `gen_run` renders a **Clip** to `output/pending/` without manual intervention.
- Weekly OpenRouter spend stays ≤ 800¢, verified against `quota_usage`.
- A deliberately broken run (bad key, killed process) produces an alert within one run cycle.
- Cost per **Clip** ≤ 150¢, measured on the live run in Issue 70.
