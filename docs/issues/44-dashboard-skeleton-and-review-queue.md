# Issue 44 — Dashboard skeleton + review queue

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/web-review-calendar-dashboard.md` — Web Review / Calendar Dashboard (v1).
Decisions of record: `CONTEXT/Grilling/2026-05-31-web-review-dashboard.md` (D1–D5),
`CONTEXT/CONTEXT.md` (glossary: **Review stage**).

## What to build

The walking skeleton of the read-only dashboard, end-to-end, plus its first and most
important section — the **review queue** with in-browser video preview. This slice
establishes the whole stack so the calendar (Issue 45) and uploaded/header (Issue 46)
sections just extend it.

End-to-end behavior:

- `python -m src.dashboard` launches a local FastAPI/uvicorn server bound to **127.0.0.1**
  (no auth — the localhost bind is the boundary) and serves one static HTML page.
- An **output-dir scanner** locates each **Clip**'s MP4 by scanning the `output/`
  directories (`pending/`, `approved/`, `rejected/`, `dry_run/`) — the file is found by
  scanning, never by trusting the possibly-stale `clips.output_path`.
- A **pure view-model function** reconciles `clips` rows (via Repository read methods) with
  the scanner's results to assign each clip a derived **Review stage** (Awaiting review /
  Approved-scheduled / Published / Rejected), and assembles the **review queue**: the clips
  whose file is in `output/pending/`, each with title, hook, content kind, and its
  Tue/Thu slot (`publish_at_utc` shown in Asia/Singapore time).
- The page renders the review queue as cards, each with an HTML5 `<video>` that streams the
  clip from a **range-aware MP4 endpoint restricted to files under `output/`** (a path
  outside `output/` is refused).
- A manual Refresh re-pulls the current state.

v1 is **read-only**: no DB writes, no file moves, no pipeline invocation. The view-model
is pure over an injected `reader` + `scanner` so it is fully unit-testable without a server,
a real DB, or the network.

## Acceptance criteria

- [ ] `python -m src.dashboard` serves the page on `127.0.0.1` only (not reachable on the
      LAN); no auth.
- [ ] The output-dir scanner maps each clip to the dir/path currently holding its MP4
      across pending/approved/rejected/dry_run; a stale `output_path` is never used.
- [ ] The view-model is a pure function over injected `reader` + `scanner`, returning the
      derived **Review stage** per clip and the assembled review queue.
- [ ] **Review stage** derivation: file in `pending/` → Awaiting review; in `approved/` +
      `publish_at_utc` set + no `youtube_video_id` → Approved/scheduled; `youtube_video_id`
      set → Published; `status=rejected_*` (or in `rejected/`) → Rejected.
- [ ] The review queue shows each pending clip's title, hook, content kind, and its
      `publish_at_utc` in Asia/Singapore time, with a working in-browser `<video>` preview.
- [ ] The MP4 endpoint is range-aware and **refuses any path outside `output/`**
      (path-traversal guard).
- [ ] v1 performs **no** DB write, file move, or pipeline/billed call.
- [ ] Tests: M1 Review-stage derivation (injected fakes, all four stages + stale-path
      ignored); M1a scanner (temp dir → correct mapping, ignores non-MP4s, clip in no dir);
      M2 `TestClient` smoke (view endpoint 200 + JSON shape; MP4 endpoint serves an
      `output/` file and refuses an outside path). No real DB/server/network; no
      billed/generation code.

## Blocked by

None - can start immediately.
