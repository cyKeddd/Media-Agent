# Issue 48 — Dashboard v2 alerts feed

**Status:** complete
**Type:** AFK

## Parent

`docs/prds/dashboard-v2-health-first-redesign.md` — Dashboard v2 (health-first redesign +
approve/reject). Decisions of record: `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`
(D3), `CONTEXT/CONTEXT.md` (glossary: **Alert**).

## What to build

The recent-**Alerts** feed for the health-first dashboard, end-to-end.

End-to-end behavior:

- An **alerts parser** reads the tail of `logs/alerts.md` and returns structured entries —
  `{timestamp, kind, message, severity}` — newest first, bounded to a recent-N tail. It is
  pure over an injected file path, mirroring the existing output-dir scanner discipline, and
  is **tolerant of the file's mixed historical formats** (the pipe-table rows and the
  bracketed `[ISO] kind=… ` lines both appear) and of blank/malformed lines.
- A **kind→severity** mapping classifies each **Alert**: failures (e.g. `gen_run_failed`)
  → error; warnings (e.g. `loudness_warn`, `upload_quota_exceeded`) → warning; routine notices
  (e.g. `gen_run_finished`, `recovered_slot`, `publish_at_padded`) → info. Unknown kinds
  degrade to info.
- The parser result is threaded through `build_dashboard_view` into the `health` section, and
  surfaced in `/api/view`.
- The page renders an **alerts rail** (slim, newest-first) with severity color-coding, and the
  derived overall **Pipeline health** status accounts for warning-level alerts (degraded) per
  the rule established in Issue 47.

Read-only: parses a log file; no DB write, no file move, no pipeline/billed call.

## Acceptance criteria

- [ ] Alerts parser returns recent entries newest-first, bounded to a tail limit, as
      structured `{timestamp, kind, message, severity}`.
- [ ] Parser tolerates the mixed historical line formats in `logs/alerts.md` and skips
      blank/malformed lines without raising.
- [ ] kind→severity mapping classifies error / warning / info correctly; unknown kinds → info.
- [ ] `/api/view` `health` section includes the recent alerts; the page renders the alerts
      rail with severity colors.
- [ ] Overall **Pipeline health** reflects warning-level alerts as degraded (when no Run has
      failed), consistent with Issue 47's derivation.
- [ ] No DB write, file move, or billed/generation call.
- [ ] Tests: **M3** alerts parser against a temp `alerts.md` (mixed formats + malformed lines
      + tail limit + severity mapping); **M1** the alerts portion of the health rollup
      (injected fakes). No real DB/server/network; no billed code.

## Blocked by

- Issue 47 — Dashboard v2 skeleton + run-status health band (provides the `health` section,
  command-center scaffold, and overall-status derivation this extends).
