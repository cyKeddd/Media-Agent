# Issue 49 — Dashboard v2 work-area panels restyled

**Status:** complete
**Type:** AFK

## Parent

`docs/prds/dashboard-v2-health-first-redesign.md` — Dashboard v2 (health-first redesign +
approve/reject). Decisions of record: `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`
(D4, D8), `docs/adr/0005-dashboard-dependency-light-frontend.md`,
`CONTEXT/CONTEXT.md` (glossary: **Review stage**).

## What to build

Port the existing v1 content — review queue, calendar, uploaded list — into the v2
command-center layout with the design system, still **read-only**.

End-to-end behavior:

- The **work area** becomes two columns: the **review queue** (clips **Awaiting review**)
  with a large in-browser `<video>` preview, title, hook, content kind, shot mix, and Tue/Thu
  slot (Asia/Singapore time) on the left; the publish **calendar** on the right.
- The **calendar** keeps month navigation, renders entries in Asia/Singapore time color-coded
  by **Review stage**, and supports click-to-jump to a clip.
- The **uploaded list** is restyled and **collapsed at the bottom** (expandable), each entry
  linking to YouTube and showing live vs scheduled-on-YouTube.
- All sections use the design-system cards/typography/colors from Issue 47; the MP4 preview
  endpoint stays range-aware and **restricted to files under `output/`** (path-traversal
  guarded).
- The view-model continues to derive **Review stage** by reconciling the scanned `output/`
  directory with DB fields; the file is located by scanning, never by trusting a stale
  `clips.output_path`.

Read-only: no DB write, no file move (the approve/reject action arrives in Issue 50), no
pipeline/billed call.

## Acceptance criteria

- [ ] Review queue, calendar, and uploaded list render inside the command-center two-column
      work area + collapsed-uploads layout with the design system from Issue 47.
- [ ] Review-queue cards show title, hook, content kind, shot mix, and slot (SGT) with a
      working `<video>` preview.
- [ ] Calendar: month navigation, SGT entries color-coded by **Review stage**, click-to-jump
      to a clip.
- [ ] Uploaded list: collapsed/expandable, YouTube links, live vs scheduled-on-YouTube
      indicator.
- [ ] MP4 endpoint remains range-aware and refuses any path outside `output/`.
- [ ] **Review stage** still derived from the scanned dir (stale `output_path` never used).
- [ ] No DB write, file move, or billed/generation call.
- [ ] Tests: existing v1 view-model + scanner tests still pass; **M5** `TestClient` smoke
      asserts the `/api/view` JSON shape for the restyled sections. No real DB/server/network;
      no billed code.

## Blocked by

- Issue 47 — Dashboard v2 skeleton + run-status health band (provides the command-center
  layout and design system this fills).
