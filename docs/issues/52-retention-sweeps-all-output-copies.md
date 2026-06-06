# Issue 52 — Retention sweeps all output/ copies of an uploaded Clip (+ clean existing orphans)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS2. Decisions of record:
`CONTEXT/CONTEXT.md` (glossary: **Clip**, **Review stage**).

## What to build

The retention post-upload sweep currently deletes only the single file named in
`clips.output_path`, so a duplicate copy of an uploaded **Clip** left in another `output/`
subdir is stranded forever (this is how the two known orphans in `output/pending/` arose — they
are also present in `output/approved/`, for **Clips** already published). Broaden the sweep to
clean **every** `output/` copy.

End-to-end behavior:

- The post-upload candidate finder, for each `clips` row with `status='uploaded'` and
  `updated_at <=` the `output_post_upload` TTL threshold, derives the **basename** from
  `output_path` and collects that basename wherever it exists across `output/pending/` and
  `output/approved/` — not only the directory named in `output_path`.
- The existing under-root unlink guard (`_safe_unlink`) and the `output_post_upload` threshold
  are reused unchanged. `output/rejected/` keeps its independent mtime-based TTL, untouched.
- The two existing orphans (`2026-06-02__slot_0900__genetic_leap_reverse_aging_51fa.mp4` and
  `…google_just_open_sourced…ac07.mp4` in `output/pending/`) are cleaned once — via a small
  one-shot script or a documented manual deletion; both **Clips** are already published.

## Acceptance criteria

- [ ] For an uploaded **Clip** with copies in both `pending/` and `approved/`, the sweep lists
      and deletes **both** (subject to the TTL), not just the `output_path` one.
- [ ] The `output_post_upload` TTL is respected — nothing is deleted before the threshold.
- [ ] `_safe_unlink` still refuses any path resolving outside the project root / `output/`.
- [ ] `output/rejected/` behavior is unchanged (its own mtime TTL).
- [ ] The two known orphan files are removed (one-shot script committed, or deletion documented
      in the handoff).
- [ ] Tests: the broadened finder returns duplicate copies across subdirs and honors the TTL;
      a not-yet-expired uploaded clip is not swept; the out-of-root guard holds. No real deletes
      outside a temp tree.

## Blocked by

- None — can start immediately.
