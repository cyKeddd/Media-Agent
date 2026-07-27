# Issue 64 — Nano Banana 2 still provider

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 2 (High)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS2.
Decision of record: [ADR-0009](../adr/0009-image-first-shot-generation.md).

## What to build

A concrete **Still provider** producing a **Generated still** from OpenRouter's
`google/gemini-3.1-flash-image` (Nano Banana 2, ≈$0.004/still, released 2026-06-18).

Scope:

- `src/image_gen/nano_banana.py` implementing the `StillProvider` ABC from Issue 63.
- Requests a 9:16 still at or above the **Shot normalization** target (ADR-0002 conforms to
  1080×1920, so the still must be at least that on its short edge to avoid upscaling).
- Applies the channel's style directive so all four stills of a **Clip** share a look — reuse the
  existing style suffix mechanism rather than inventing a second one.
- Persists to the existing image cache (`data/images/`, `paths.images_dir`) with the same retention
  behaviour as licensed images (`retention.images: 30`).
- **Meters cost** into `quota_usage` with `provider='openrouter'` and the `script_id` attribution
  the per-clip cap relies on, so stills count against INV-2 alongside video.
- Enforces INV-3: refuse a still whose projected cost exceeds 5¢, and refuse when the **Clip**'s
  accumulated still spend would exceed 20¢.
- Enforces INV-8: reject a prompt that names an identifiable living person before calling the API.
  Reuse the existing no-living-individuals check rather than writing a second one.
- Transient failures retry per INV-12; `401`/`403` fail fast per Issue 61.

## Invariants

- **INV-3** — One **Generated still** ≤ 5¢; all stills for one **Clip** ≤ 20¢.
- **INV-2** — Still spend is attributed to the `script_id` and counts toward the 150¢ per-clip cap.
- **INV-8** — No still prompt may name or depict an identifiable living person.
- **INV-10** — Implements `StillProvider`; swappable by config.
- **INV-12** — 5xx/timeout retry ×3; `401`/`403` abort immediately.

## Acceptance criteria

- [ ] `src/image_gen/nano_banana.py` implements `StillProvider` and returns a `StillResult` with a
      real `path` and a populated `cost_cents`.
- [ ] Model ID `google/gemini-3.1-flash-image` is read from config, not hardcoded.
- [ ] Output still is ≥ 1080 px on its short edge and 9:16.
- [ ] Cost is written to `quota_usage` with `provider='openrouter'` and the correct `script_id`.
- [ ] A still projected above 5¢ is refused; a **Clip** already at 20¢ of stills refuses the next.
- [ ] A prompt naming a living person is rejected **before** any HTTP call (assert call count 0).
- [ ] Stubbed `401` makes exactly one attempt; stubbed `503` retries.
- [ ] Tests use a fake HTTP layer — **no live API calls, no real spend.**

## Blocked by

- Issue 63 (`StillProvider` ABC), Issue 62 (cost-cap config keys).

## Verification-command

```
pytest tests/test_nano_banana_provider.py -q
```
