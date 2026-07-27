# Issue 63 — `Provider` ABC accepts a first-frame image

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 2 (High — structural prerequisite for all of WS2)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS2.
Decision of record: [ADR-0009](../adr/0009-image-first-shot-generation.md).

## What to build

Teach the video-provider abstraction about image-to-video.

`src/ai_gen/base.py` currently defines:

```python
def submit(self, prompt: str, *, duration_s: int = 5, aspect_ratio: str = "9:16") -> str
```

There is no way to pass a first frame, so every **Shot** is text-to-video. ADR-0009 makes
image-to-video the default path, so the ABC must carry the still.

Scope:

- `Provider.submit()` gains an optional keyword `first_frame_path: Path | None = None`.
- A provider that cannot do image-to-video raises a clear, typed error when given a first frame —
  it must not silently ignore it and bill for an unconditioned text-to-video generation. Silent
  fallback here would spend money producing the wrong thing.
- The existing `src/ai_gen/openrouter_kling.py` implements the new argument (Kling v3.0 supports
  first-frame conditioning), keeping its current text-to-video behaviour when the argument is
  `None`.
- `wait_for_completion`, `poll`, and `download` are unchanged.
- Introduce a `StillProvider` ABC in a new `src/image_gen/base.py`: one abstract
  `generate(prompt: str, *, aspect_ratio: str, dest: Path) -> StillResult`, with `StillResult`
  carrying at least `path` and `cost_cents`. The concrete implementation lands in Issue 64; this
  issue only establishes the seam.

This is a pure refactor — no behaviour change to existing clips, no new billing.

## Invariants

- **INV-10** — Every video generator implements `Provider`; every still generator implements
  `StillProvider`. Swapping either is a config-only change with no downstream pipeline edit.

## Acceptance criteria

- [ ] `Provider.submit()` accepts `first_frame_path: Path | None = None`.
- [ ] Calling `submit(first_frame_path=...)` on a provider that does not support it raises a typed
      error (not a silent no-op), asserted by a test.
- [ ] `openrouter_kling` accepts the argument and includes the image in its request payload when
      present; when `None` its request payload is byte-identical to today's (regression guard).
- [ ] `src/image_gen/base.py` defines `StillProvider` and `StillResult` with `path` and
      `cost_cents`.
- [ ] All existing `tests/ai_gen` tests pass unchanged.

## Blocked by

- None — independent of WS1 and safe to run in parallel with it.

## Verification-command

```
pytest tests/ai_gen tests/test_provider_first_frame.py -q
```
