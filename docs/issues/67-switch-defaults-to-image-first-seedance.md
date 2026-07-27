# Issue 67 — Switch runtime defaults to image-first + Seedance

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 2 (High — the flip that makes WS2 take effect)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS2.
Decision of record: [ADR-0009](../adr/0009-image-first-shot-generation.md).

## What to build

Flip the runtime defaults so the ladder from Issue 66 is the production path, and reconcile the
documentation that still describes the old one.

Scope:

- `config.yaml`:
  - `ai_gen.model: bytedance/seedance-2.0-fast` with its per-second rate.
  - Still-generation block: model `google/gemini-3.1-flash-image`, the INV-3 ceilings, and
    `enabled: true`.
  - `clips_per_day` / `upload_weekdays` set for **5 Clips/week** (D2).
  - Kling retained as a commented, ready-to-swap alternative — the point of INV-10 is that
    reverting is a config edit.
- Docs reconciled to match reality (they currently describe Kling text-to-video as the only path):
  `CLAUDE.md` (stack, architecture diagram, locked decisions), `agents.md` (module responsibilities),
  `skills.md` (library rationale), `CONTEXT/CONTEXT.md` (add **Generated still** and **Still
  provider** to the glossary), `CONTEXT/INDEX.md` (phase rows).
- `bootstrap --check` verifies the configured video and still models are reachable — a check-time
  failure is much cheaper than a Sunday 02:00 failure.

Cost expectation to state in `CLAUDE.md`: ~88¢ per **Clip** (4 stills ≈ 2¢ + 16 s Seedance ≈ 86¢),
5 **Clips**/week ≈ $4.40 against the 800¢ weekly ceiling.

## Invariants

- **INV-1 / INV-2 / INV-3** — Configured ceilings are 800¢ weekly, 150¢ per **Clip**, 5¢/20¢ for
  stills.
- **INV-10** — Reverting to Kling is a config-only change; prove it with a test that constructs the
  provider from config alone.

## Acceptance criteria

- [ ] `config.yaml` selects Seedance for video and Nano Banana 2 for stills, with all INV ceilings
      present.
- [ ] Cadence config expresses 5 **Clips**/week.
- [ ] A test builds the video provider purely from config and gets Seedance; overriding the config
      value alone yields Kling (INV-10 proof).
- [ ] `bootstrap --check` fails clearly when a configured model ID is unreachable.
- [ ] `CLAUDE.md`, `agents.md`, `skills.md`, `CONTEXT/CONTEXT.md`, `CONTEXT/INDEX.md` describe the
      image-first path; no doc still claims Kling text-to-video is the only generator.
- [ ] `CONTEXT/CONTEXT.md` defines **Generated still** and **Still provider**.
- [ ] `progress.md` updated per the working agreement.

## Blocked by

- Issue 66 (the ladder must exist before it becomes the default).

## Verification-command

```
pytest tests/test_config_image_first.py -q
```
