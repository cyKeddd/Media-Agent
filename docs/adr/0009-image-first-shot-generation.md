# ADR-0009 — Every Shot is generated image-first, then animated image-to-video

**Status:** Accepted
**Date:** 2026-07-27
**Context:** Surfaced while grilling the "polish everything up" effort (`/part1`, 2026-07-27),
after finding the pipeline had produced no **Clip** since 2026-06-02.

## Context

Pivot.6 generated each **AI-video shot** with a *text-to-video* call: the **Script**'s per-shot
prompt went straight to Kling, which invented both composition and motion in one step. Pivot.7
added **Real-image shots** — a **Licensed source** still with Ken Burns motion — to reduce cost
and improve factual grounding, giving the **Hybrid clip**.

Two problems remained:

1. **Text-to-video is the least controllable and most expensive way to buy a frame.** Composition
   is re-rolled on every retry, style drifts between the four **Shots** of one **Clip**, and a bad
   composition can only be fixed by re-billing the full video call.
2. **A licensed miss degraded the shot.** Per ADR-0003 the autonomous path uses licensed sources
   only; when the lookup missed, the **Real-image shot** fell back to a generic text-to-video
   **AI-video shot** with no visual relationship to the story.

Meanwhile the economics changed. As of 2026-07-27 on OpenRouter:
`bytedance/seedance-2.0-fast` is **$0.0538/s** with first-frame/last-frame image-to-video, and
`google/gemini-3.1-flash-image` (Nano Banana 2, released 2026-06-18) generates a still for
**≈$0.004**. A still is roughly **50× cheaper than the video second it conditions.**

## Decision

**Every Shot is produced as a still first, then animated by an image-to-video call.** Text-to-video
becomes the last-resort fallback, not the default path.

The **Shot** pipeline becomes a three-step ladder, evaluated per **Shot**:

1. **Source the still.**
   - If the **Shot** names a real entity (product, company, logo) → attempt the **Licensed source**
     lookup (`logo`, `wikimedia`, `openverse`) exactly as ADR-0003 requires.
   - On a licensed miss, or when the **Shot** names no real entity (abstract, atmospheric,
     transitional) → generate a **Generated still** with Nano Banana 2.
2. **Animate the still.** Feed it as the **first frame** to the image-to-video provider
   (`bytedance/seedance-2.0-fast`), which returns the ~4 s **Shot**.
3. **Fallback.** If the still step fails entirely, fall back to text-to-video as today.

Two new terms enter the glossary: **Generated still** (an AI-generated still image used as an
image-to-video first frame) and **Still provider** (the ABC that produces one).

`Provider.submit()` gains an optional `first_frame_path` argument; a parallel `StillProvider` ABC
is introduced for still generators. Both stay swappable by config (INV-10).

**The licensed-first rule is strengthened, not relaxed.** A **Generated still** renders a
*plausible* product, not *the* product. For an AI-news channel, depicting a hallucinated iPhone in
a story about that iPhone is a credibility failure, so a **Generated still** may never pre-empt a
**Licensed source** that would have resolved (INV-7).

Ken Burns motion is retained only as the fallback when image-to-video is unavailable; the
image-to-video call supersedes it, producing genuine motion from the same still.

## Consequences

**Positive:**
- **Cost per Clip falls from ~$2.02 (Kling std text-to-video) to ~$0.88**, so the $8/week budget
  buys ~5 **Clips**/week with retry headroom instead of 2.
- **Style coherence across a Clip** — all four stills can be generated under one style directive,
  and the video model inherits composition rather than reinventing it.
- **Cheap iteration.** A bad composition is re-rolled for ~$0.004 instead of ~$0.50.
- **Licensed misses stop degrading the Shot** — they degrade to a styled **Generated still**,
  which is far closer to the intended frame than a generic text-to-video clip.

**Negative:**
- **A third external dependency** in the billable path (still model), with its own failure modes.
  Mitigated by the ladder's text-to-video fallback.
- **Two ABCs to maintain** (`Provider`, `StillProvider`) and a `first_frame_path` argument that
  every existing provider must accept.
- **A new credibility hazard**: it is now cheap to render convincing fake product imagery. INV-7
  and INV-8 are the guardrails; they are enforced at shot-routing and unit-tested, not left to
  prompt discipline.

## Alternatives considered

1. **Keep text-to-video, just upgrade to Kling v3.0 pro.** One-line change, but +33% cost for ~3
   **Clips**/week and no gain in controllability or style coherence. Rejected on cost-per-quality.
2. **Nano Banana 2 for every still, drop licensed sourcing.** Simplest pipeline and the best style
   consistency, but abandons factual grounding for a news channel. Rejected by the user.
3. **Stills + Ken Burns only, no video model at all.** ~$0.02/**Clip**. Rejected: a Short built
   entirely from panning stills reads as a slideshow.

## References

- `CONTEXT/CONTEXT.md` — **Shot**, **Shot kind**, **Real-image shot**, **Licensed source**,
  **Generated still**, **Still provider**.
- [ADR-0002](0002-canonical-shot-normalization-in-assembler.md) — **Shot normalization** still
  applies; image-to-video output must be conformed before **Stitching**.
- [ADR-0003](0003-licensed-only-image-sourcing-for-autonomous-ships.md) — licensed-first, upheld
  and strengthened here.
- [ADR-0008](0008-hermes-director-authors-scripts-rows.md) — **Directed scripts** flow through this
  ladder unchanged; the director gets no exemption.
- `src/ai_gen/base.py` (`Provider`), `src/image_fetch/` (licensed sourcing),
  `src/assembler/ken_burns.py` (now fallback-only).
- Pricing verified 2026-07-27: <https://openrouter.ai/bytedance/seedance-2.0-fast>,
  <https://openrouter.ai/google/gemini-3.1-flash-image>.
