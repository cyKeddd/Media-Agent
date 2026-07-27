# Issue 68 — Subtitle and typography restyle

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 3 (Medium)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS3.

## What to build

Modernise the burned-in subtitles. This was one of the two polish levers the user picked.

Current style (`src/subtitles/line_ass.py`): Impact 120 px, plain white
(`&H00FFFFFF`), 8 px black outline, `\pos(540,1500)`, `an5`, 28 chars/line, 100 ms fade-in. It is
legible but reads as default-ASS — the look of a 2019 auto-caption, not a current Shorts channel.

Scope:

- Replace Impact with a heavier contemporary face, bundled or confirmed present on the render box.
  **Verify the font actually resolves in the ffmpeg/libass render** — a missing font silently
  falls back and the burn looks nothing like the design.
- Add a keyword accent colour: the scripter already identifies a hook; emphasise the numerically or
  semantically salient token per line in the accent colour while the rest stays white.
- Tighten the reveal: shorter fade, slight scale-in on line entry.
- Keep the safe-area anchor — `\pos(540,1500)` sits above the YouTube Shorts UI chrome. Do not move
  it without checking the overlay bounds.
- Keep the ≤ 28 chars/line wrap and the word-boundary break.
- Keep the existing Whisper forced-alignment timing source unchanged.

Because ASS output is a pure string transformation, this is testable without rendering video —
assert on the generated ASS. **Also produce one real burned MP4** for the ticket evidence, because
a style that only passes string assertions has not actually been seen.

## Invariants

- **INV-11** — Subtitle generation adds no measurable time to the assembly budget.
- Existing: subtitles remain burned-in (no sidecar), line-at-a-time, aligned from the TTS mp3.

## Acceptance criteria

- [ ] Generated ASS uses the new font, size, and outline values from module constants.
- [ ] The accent colour is applied to the emphasised token and only that token; the rest of the
      line keeps the primary colour.
- [ ] A line with no emphasis candidate renders entirely in the primary colour (no crash, no
      empty override block).
- [ ] Line wrapping stays ≤ 28 characters and breaks on word boundaries (regression guard).
- [ ] `\pos(540,1500)` and `an5` are unchanged.
- [ ] ASS metacharacter escaping still holds for `\`, `{`, `}` — the accent override must not be
      escapable by narration text (a narration containing `{` must not corrupt the style block).
- [ ] Ticket evidence includes one rendered MP4 confirming the font resolved in libass.

## Blocked by

- None — independent of WS1 and WS2, safe to run in parallel.

## Verification-command

```
pytest tests/test_line_ass_style.py -q
```
