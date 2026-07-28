# Handoff — issues-59-69-parallel-delivery
**Date:** 2026-07-28
**Project:** media-agent
**Working directory:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`

## What was accomplished this session

- **Shipped all 11 codeable issues from the resurrection + image-first PRD (59–69)** — every ticket
  that was in Agent Ready. 13 commits, `ba495a7` → HEAD. Spec per issue in `docs/issues/NN-*.md`;
  per-ticket evidence in the Linear comments on MED-5…MED-15.
- **Delivered in 6 dependency-ordered waves via parallel subagents** (max 3, depth 1, disjoint file
  lanes). The parent held the gate: every Verification-command was re-run by the parent after the
  agent's final edit, never accepted from the agent's summary.
- **Found and fixed the bug that made the whole spend-cap workstream a no-op.** `generate_shots`
  recorded `quota_usage` only when `script_id` was truthy, so the ledger was empty and any ceiling
  built on it would read 0 forever and never fire. Proven pre-existing by running the test in a
  detached worktree at pristine `HEAD 7c0e246` before touching anything. Fixed in MED-8 as a
  prerequisite to building the weekly ceiling on top.
- **Closed three "green tests, unmet criterion" gaps** the subagents left, each found by reading the
  code rather than the report: MED-7 never wired the run-level `auth_failed` abort (the string
  existed only in a docstring); MED-10 left the combined per-clip cap unenforced across the
  video + still buckets; MED-13's flip would have been cosmetic because the provider was hardcoded
  and the cost projection was pinned to Kling's 67¢.
- **Reconciled all docs to what the code actually does**, including the parts that are less
  flattering than the PRD — see "Open decisions / blockers".
- Also fixed an unrelated global Claude Code breakage (`ANTHROPIC_BASE_URL` written to user-scope
  `settings.local.json`, 401ing every session) and built the `kimi` command properly. Outside this
  repo — see `~/.claude/kimi.ps1`.

## Current state

- **Linear:** MED-5…MED-15 all in **Debugger Ready** with evidence comments and state readbacks.
  MED-16 (Issue 70) still **Agent Ready** — deliberately never started.
- **Tests:** full suite **977 passed / 18 failed / 14 collection errors**. Baseline before this
  effort was **920 / 19 / 14**. One baseline failure fixed (`test_config_p4::test_config_yaml_loads_cleanly`),
  **zero new failures**. The 14 collection errors are legacy v1 modules missing `yt_dlp` / `nvidia`
  and are unrelated to this work.
- **Runtime defaults are now image-first:** `bytedance/seedance-2.0-fast` video + Nano Banana 2
  stills, provider built from config by `src/ai_gen/factory.build_video_provider` (called at
  `gen_run.py:445`), ~88¢/Clip, 5 Clips/week, 800¢ rolling weekly ceiling.
- **Nothing has been run live. Zero real spend this session.** `output/pending/` untouched,
  `quota_usage` unchanged, no provider was ever called — every test uses fakes.
- **`.env` still holds the 12-char placeholder key.** Verified this session. `bootstrap --check`
  now fails loudly on it (Issue 59) instead of silently at billing time.
- Working tree clean apart from a pre-existing `.env.example` whitespace edit that predates this
  session and was deliberately left alone.

## Immediate next action

Put a **real, funded, rotated** `OPENROUTER_API_KEY` in `.env`, then run the zero-cost half of
Issue 70:

```powershell
python -m src.bootstrap --check
python -m src.gen_run --dry-run --clips 1   # must exit 0 with ZERO spend in quota_usage
```

Do **not** run `--clips 1` for real without the user's explicit go-ahead — MED-16 is the only
ticket with spend authority (≤150¢), and steps 7–8 are human review.

## Open decisions / blockers

1. **`ai_video` shots do not traverse the ADR-0009 ladder.** `route_shot` handles that case and is
   tested in isolation, but `route_shot` appears nowhere in `gen_run.py` — `_generate_clip` still
   batches `ai_video` shots straight to text-to-video. Real-image shots *are* image-first. Docs say
   this explicitly rather than claiming otherwise. Needs a follow-up ticket; rewiring touches the
   concurrent-submission machinery in `ai_gen/runner.py` and the call-count assertions in
   `test_gen_run.py` / `test_hybrid_gen_run.py`.
2. **Every OpenRouter wire schema is an unverified assumption.** The first-frame payload shape
   (Kling + Seedance) and the Nano Banana request/response (`POST /api/v1/images`,
   `data[].b64_json`, `usage.cost`) are modelled on the closest documented precedent and locked by
   tests. None has touched the live API. **Issue 70's first billed run is where a wrong schema
   surfaces** — check this before trusting it.
3. **Issue 70 blocked** on a funded key + explicit spend authority + human review of the MP4.
4. **No follow-up tickets were filed** for items 1–2. Filing is a tracker write the user hasn't
   asked for; memory says GitHub is the create surface (sync mirrors to Linear MED) and
   `gh issue create` has been denied by the permission classifier before.

## Artifacts created this session

| Artifact | Path | Notes |
|---|---|---|
| Provider factory | `src/ai_gen/factory.py` | Config-driven provider + `estimate_shot_cost_cents` |
| Seedance provider | `src/ai_gen/openrouter_seedance.py` | i2v, 22¢/4 s shot |
| Still provider ABC | `src/image_gen/base.py` | `StillProvider` / `StillResult` |
| Nano Banana provider | `src/image_gen/nano_banana.py` | Generated stills, INV-3/INV-8 |
| Routing ladder | `src/scripter/shot_router.py` | INV-7 + combined per-clip ceiling |
| Liveness alerts | `src/observability/liveness.py` | `liveness_stalled`, ≤1/day |
| 11 new test files | `tests/test_*.py` | ~190 new tests, all fakes, no spend |
| Doc reconciliation | `CLAUDE.md`, `agents.md`, `skills.md`, `CONTEXT/CONTEXT.md`, `CONTEXT/INDEX.md`, `progress.md` | Image-first path + known gaps |

## Skills used this session

| Skill | File | Purpose |
|---|---|---|
| `linear-pipeline` | `C:\Users\cryptix\.claude\skills\linear-pipeline\SKILL.md` | Stage protocol, Linear-only writes, readback-after-write |
| `handoff` | `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` | This document |

Not used: `/grill-with-docs`, `/to-prd`, `/to-issues` — the grill, PRD and issues were produced by
the **2026-07-27** session. This session was pure delivery against them.

## Suggested skills for next session

- `/part3` → `C:\Users\cryptix\.claude\skills\part3\SKILL.md` — 11 tickets are sitting in Debugger
  Ready and **nothing has been independently graded**. Maker ≠ checker: the parent that drove these
  agents is not a valid grader for them. Start here.
- `/controlled-ticket-delivery` → for Issue 70, which is budget-capped and touches real spend.
- `/qa` → to file the two known gaps above as proper tickets.
