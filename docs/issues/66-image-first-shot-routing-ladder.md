# Issue 66 — Image-first shot routing ladder

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 2 (High — this is where ADR-0009's integrity rule is actually enforced)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS2.
Decision of record: [ADR-0009](../adr/0009-image-first-shot-generation.md).

## What to build

The routing ladder that makes every **Shot** image-first, and the guard that keeps **Generated
stills** from displacing real ones.

Per **Shot**, in order:

1. **Source the still.**
   - **Shot** names a real entity (product, company, logo) → attempt the **Licensed source**
     lookup (`logo`, `wikimedia`, `openverse`) via the existing `src/image_fetch/` path.
   - Licensed miss, **or** the **Shot** names no real entity (abstract / atmospheric /
     transitional) → **Generated still** via the Issue 64 provider.
2. **Animate.** Pass the still as `first_frame_path` to the configured video `Provider`.
3. **Fallback.** Still step fails entirely → text-to-video, exactly as today.

The integrity rule is the point of this issue: **a Generated still may never pre-empt a Licensed
source that would have resolved.** For any shot naming a real entity, the licensed lookup must be
*attempted and observed to miss* before Nano Banana is called. This must be enforced by the routing
code and asserted by a test, not left to prompt discipline — a hallucinated product in a news story
about that product is the credibility failure ADR-0003 exists to prevent.

Scope:

- Routing lives in the existing shot-resolution path (`resolve_shot_plan` / `_render_real_image_shot`
  in `src/gen_run.py` around lines 204–332), not in a new parallel pipeline.
- Ken Burns (`src/assembler/ken_burns.py`) becomes the **fallback** motion path when
  image-to-video is unavailable — it is not deleted.
- Each **Shot** records which rung it took (`licensed_i2v`, `generated_i2v`, `text_to_video`,
  `ken_burns`) so the dashboard and ticket evidence can show the mix.
- **Directed scripts** (ADR-0008) flow through this ladder unchanged — the Hermes director gets no
  exemption.

## Invariants

- **INV-7** — A **Shot** naming a real product, company, or logo MUST use a **Licensed source**
  when one resolves. A **Generated still** is permitted only on a licensed miss, or when the shot
  names no real entity.
- **INV-8** — No shot prompt, video or still, may name or depict an identifiable living person.
- **INV-2 / INV-3** — Still and video spend for one **Clip** stay within the per-clip and per-still
  ceilings; the ladder must check before billing, not after.
- **INV-12** — Licensed miss → **Generated still**; still failure → text-to-video.

## Acceptance criteria

- [ ] A **Shot** naming a real entity with a licensed hit → `licensed_i2v`; the still provider is
      **not** called (assert call count 0).
- [ ] A **Shot** naming a real entity with a licensed **miss** → `generated_i2v`, and the licensed
      lookup was attempted first (assert ordering).
- [ ] A **Shot** naming no real entity → `generated_i2v` without a licensed lookup.
- [ ] Still generation failure → `text_to_video` fallback, and the **Clip** still completes.
- [ ] Image-to-video unavailable → `ken_burns` fallback still produces a usable **Shot**.
- [ ] The rung taken is persisted per **Shot** and readable for evidence.
- [ ] A **Directed script**'s shots traverse the identical ladder (no director exemption).
- [ ] A shot prompt naming a living person is rejected before any billable call.
- [ ] Tests use fake image-fetch, fake still, and fake video providers — **no real spend.**

## Blocked by

- Issue 64 (still provider), Issue 65 (image-to-video provider).

## Verification-command

```
pytest tests/test_shot_routing_ladder.py -q
```
