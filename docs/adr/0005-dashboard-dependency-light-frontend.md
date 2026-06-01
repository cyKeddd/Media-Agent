# ADR-0005 — Dependency-light frontend for the dashboard (no SPA, no build step)

**Status:** Accepted
**Date:** 2026-06-01
**Context:** Surfaced while grilling the dashboard **v2** health-first redesign
(`/grill-with-docs`; grill record `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`).

## Context

The Media-Agent repo is pure Python (3.11+) with a deliberately minimal dependency set;
the dashboard v1 (Issues 44–46) is a single FastAPI app serving one hand-written static
HTML page with inline CSS/JS. The v2 redesign aims to "look good" and become a health-first
monitoring console — richer layout, status tiles, an alerts feed, and an interactive
approve/reject control. The obvious instinct for a richer UI is to reach for a frontend
framework (React/Vue + Vite). That would add a Node/npm toolchain, a build step, and a
second language ecosystem to a project that has none of those, for a tool that runs only on
`127.0.0.1` for a single operator.

## Decision

**The dashboard stays a FastAPI app serving static files with no Node/npm build step.** The
"look good" goal is met with a hand-authored CSS design system (design tokens, cards,
typography, semantic status colors) and a small amount of vanilla JS split into a few static
modules. No SPA framework, no bundler, no transpile.

## Consequences

**Positive:**
- Nothing new to install, build, or keep updated; `python -m src.dashboard` remains the only
  launch step. Matches the project's minimal-deps ethos.
- The Python view-model stays the keystone testable unit; the frontend is a thin render layer.

**Negative:**
- Rich interactivity is hand-rolled rather than component-driven; complex future UI (the v3
  control panel) may strain vanilla JS and force a revisit of this decision.

## Alternatives considered

1. **Tailwind via CDN (no build).** Faster styling, still no toolchain, but pulls a remote
   asset and brings utility-class sprawl into hand-written HTML. Rejected for v2 as
   unnecessary given a small bespoke CSS system suffices.
2. **React/Vue + Vite build.** Most powerful for rich UI, but adds a Node toolchain and a
   build artifact to a Python repo for a localhost single-operator tool. Rejected as
   disproportionate; revisit only if v3 controls demand it.

## References

- `docs/adr/0002` — canonical shot normalization (sibling architectural-shape ADR).
- `src/dashboard/` — FastAPI app, view-model, static page.
- Dashboard v1 PRD `docs/prds/web-review-calendar-dashboard.md` (D2: FastAPI + static page).
