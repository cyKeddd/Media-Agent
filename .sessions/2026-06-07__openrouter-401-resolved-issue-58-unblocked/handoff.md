# Handoff — openrouter-401-resolved-issue-58-unblocked
**Date:** 2026-06-07
**Project:** Media-Agent (Pivot.6 / Pivot.7)
**Working directory:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`

## What was accomplished this session

- **Root-caused the OpenRouter 401** blocking Issue 58's `gen_run` render. It was **not** a model-access, model-ID, or provider-swap problem (Hermes's three theories were all wrong) — a 401 is auth-level (the key was rejected); model-access failures return 403/404.
- **Verified the real key works end-to-end** against the live OpenRouter API:
  - `GET /api/v1/key` → 200, `is_free_tier:false`.
  - `GET /api/v1/credits` → `total_credits:45`, `total_usage:24.99` → **~$20 remaining**.
  - `POST /api/v1/videos` with the pipeline's exact body (`model:kwaivgi/kling-v3.0-std`, prompt, duration 5, aspect 9:16) → **202 Accepted**, job `moYdfkOhydWOokxS5MjU` rendered normally.
- Confirmed **`config.yaml` (`ai_gen.model: kwaivgi/kling-v3.0-std`), the `/api/v1/videos` flow, and `src/ai_gen/openrouter_kling.py` are all correct** — do not change them.
- Found that **the pipeline does not load `.env`** (no `load_dotenv()` in `src/`); it reads `os.environ["OPENROUTER_API_KEY"]` directly (`gen_run.py:622`, `openrouter_kling.py:54`). The `.env` line `sk-or-...9fbc` is the redacted form of the working key, but is inert — the key must be set in the actual environment.
- Diagnosed Hermes's failure: it was running with the **wrong/missing key** (handoff noted Hermes lacks `OPENROUTER_API_KEY`) and Unix paths. Produced a status prompt for Hermes clarifying it is director-only (ADR-0008), must not run `gen_run`.

## Current state

- **OpenRouter key:** valid, video-capable, ~$20 credits. One throwaway test shot (~$0.30) was billed this session (discarded; not part of any clip).
- **Directed script** `ebba0850-7d30-4ee5-aee6-8f50ffc6d18a` (topic 130, Gemini Omni) still sits in `data/state.db` `status='directed'`, narration empty — **not yet consumed/rendered**.
- **No code or config changed** this session — pure diagnosis. `gen_run` has **not** been run yet (operator to run).
- Schedulers unchanged (`gen_run` Sun 02:00 SGT, `daily_upload` daily 09:00 SGT). The scheduler environment does **not** yet have `OPENROUTER_API_KEY` set persistently — the unattended Sunday run will fail the same way unless fixed.

## Immediate next action

Run the consume pipeline from **PowerShell** (not Hermes) with the key set in the session:

```powershell
cd C:\Users\cryptix\Desktop\Work\Media-Agent-main
$env:OPENROUTER_API_KEY="<full key — the sk-or-v1-...6509fbc one>"
python -m src.gen_run --dry-run --clips 1
python -m src.gen_run --clips 1
```

Then review the MP4 in `output/pending/` (`human_review: true`). This closes Issue 58 E2E.

## Open decisions / blockers

- **Persistent key for unattended runs:** `$env:` in an interactive session does not reach Task Scheduler. Set a **User** env var (`[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "<key>", "User")`) or bake it into the scheduler XML, or the Sun 02:00 weekly run hits the same "no key" wall Hermes did. **Not yet done.**
- **Hermes cron** — still not configured; should run Saturday SGT (before Sunday `gen_run`) per `docs/hermes-director-contract.md`.
- **Issue 58** remains partial until `gen_run` renders the directed clip and gates pass.

## Artifacts created this session

| Artifact | Path | Notes |
|---|---|---|
| This handoff | `.sessions/2026-06-07__openrouter-401-resolved-issue-58-unblocked/handoff.md` | Diagnosis record |
| Hermes status prompt | (in chat) | Tells Hermes the 401 is resolved + director-only role |

No source/config files were modified.

## Skills used this session

| Skill | File | Purpose |
|---|---|---|
| handoff | `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` | This document |
| push-on-task-complete | `C:\Users\cryptix\.claude\skills\push-on-task-complete\SKILL.md` | Commit + push session state |

## Suggested skills for next session

- `/handoff` — after `gen_run` E2E verification closes Issue 58.
- Hermes operator: director cron setup (no repo skill; `hermes cron create`).
