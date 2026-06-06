# Issue 53 — Dashboard locates a Clip's file by output_path basename (slug fallback)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS2. Decisions of record:
`CONTEXT/CONTEXT.md` (glossary: **Review stage**, **Clip**).

## What to build

The dashboard re-derives a filename **slug** (from `title_slug` or by recomputing from
`suggested_title`) to locate a **Clip**'s MP4 on disk, while the rest of the pipeline
(`daily_upload`, `slot_planner`) trusts `clips.output_path`. This is a latent fragility: if the
recomputed slug drifts from the slug baked into the filename, the **Clip** fails to resolve.
Make the dashboard trust `output_path` like everything else.

End-to-end behavior:

- The output scanner gains a basename index (`by_basename`: filename → `(subdir, path)`), built
  over all `output/` subdirs with the same subdir-rank tie-break already used for the slug index.
- The **Clip**→file resolver's match order becomes: existing `by_clip_id` (for
  `__unscheduled__{clip_id}__…` files) → **`by_basename[Path(output_path).name]`** → `by_slug`
  (kept only as a fallback for rows with no `output_path`).
- The subdir always comes from where the file actually sits on disk, so the derived **Review
  stage** (Awaiting review / Approved-scheduled / Published / Rejected) is unaffected by a stale
  `output_path` *directory* (e.g. a file dragged pending→approved before `daily_upload` rewrites
  the path).

## Acceptance criteria

- [ ] `ScanResult` exposes `by_basename`; ties across subdirs resolve to the highest-ranked
      subdir (approved > pending > rejected > dry_run), consistent with `by_slug`.
- [ ] The resolver matches a slot-renamed **Clip** by `output_path` basename even when its
      `title_slug` is null and the recomputed slug would differ.
- [ ] The subdir returned reflects the file's actual location on disk, not `output_path`'s
      directory; the derived **Review stage** stays correct after a pending→approved move.
- [ ] Slug matching still works as a fallback when `output_path` is null.
- [ ] Tests: scanner `by_basename` indexing + tie-break; resolver basename-first precedence;
      subdir-from-disk for a file whose `output_path` points elsewhere; slug fallback path.

## Blocked by

- None — can start immediately.
