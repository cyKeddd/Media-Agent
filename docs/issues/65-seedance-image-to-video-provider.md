# Issue 65 — Seedance 2.0 Fast image-to-video provider

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 2 (High)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS2.
Decision of record: [ADR-0009](../adr/0009-image-first-shot-generation.md).

## What to build

A concrete `Provider` for OpenRouter's `bytedance/seedance-2.0-fast` — **$0.0538/s**, with
first-frame and last-frame image-to-video support. At ~4 s per **Shot** this is ~21.5¢/shot and
~86¢ per 16 s **Clip**, against ~$2.02 for the current Kling v3.0 std text-to-video path.

Scope:

- `src/ai_gen/openrouter_seedance.py` implementing `Provider` (`submit`, `poll`, `download`),
  including the `first_frame_path` argument from Issue 63.
- Model ID and per-second price read from config — the cost projection that INV-1/INV-2 depend on
  must not be a magic number in code.
- `cost_cents` on `ShotResult` computed from actual generated duration, rounded **up**, so the
  ledger never under-reports spend.
- Output is 9:16. Whatever resolution/fps Seedance returns, **Shot normalization** (ADR-0002)
  conforms it to `output_resolution` / `output_fps` before **Stitching** — do not assume it matches
  Kling's 720×1280 @ 24 fps. Confirm the real values from a stubbed response fixture and record
  them in the ticket evidence.
- Transient failures retry per INV-12; `401`/`403` fail fast per Issue 61.
- Kling remains available and selectable by config — this issue adds a provider, it does not delete
  one.

## Invariants

- **INV-10** — Implements `Provider`; selecting it is a config-only change.
- **INV-2 / INV-1** — Reported `cost_cents` is the value the per-clip and weekly caps meter on;
  it must be derived from real duration and rounded up.
- **INV-12** — 5xx/timeout retry ×3; `401`/`403` abort immediately.
- **INV-11** — One **Shot**'s submit+poll ≤ 10 minutes (existing `timeout_s=600`).

## Acceptance criteria

- [ ] `src/ai_gen/openrouter_seedance.py` implements `Provider` including `first_frame_path`.
- [ ] Model ID `bytedance/seedance-2.0-fast` and the per-second rate come from config.
- [ ] `submit()` with a first frame includes the image in the payload; without one it submits
      text-to-video.
- [ ] `cost_cents` for a 4 s shot at $0.0538/s is 22 (rounded up from 21.52), asserted exactly.
- [ ] Stubbed `401` makes exactly one attempt; stubbed `503` retries ×3.
- [ ] A stubbed timeout surfaces `TimeoutError` from `wait_for_completion` rather than hanging.
- [ ] Existing Kling provider tests still pass — Kling is not removed.
- [ ] Tests use a fake HTTP layer — **no live API calls, no real spend.**

## Blocked by

- Issue 63 (`first_frame_path` on the ABC).

## Verification-command

```
pytest tests/test_seedance_provider.py tests/ai_gen -q
```
