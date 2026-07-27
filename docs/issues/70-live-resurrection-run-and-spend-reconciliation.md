# Issue 70 — Live resurrection run + spend reconciliation (HITL)

**Status:** ready-for-agent
**Type:** HITL — involves real spend and human review
**Priority:** 1 (Urgent — this is the gate that proves the channel is actually alive)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS5.

## What to build

Not code — **proof**. Everything upstream is verified against fakes; this issue verifies the
pipeline against reality, and is the only issue authorised to spend money.

**Spend authority:** this issue bills real OpenRouter credit. It requires the user's explicit
go-ahead at the point of running, and a funded, correctly-shaped `OPENROUTER_API_KEY` in `.env`
(Issue 59 makes a malformed key fail at check time). Budget for this issue: **≤ 150¢** — one
**Clip**.

Sequence, stopping at the first failure:

1. `python -m src.bootstrap --check` — passes, including the new key-shape and model-reachability
   checks.
2. `python -m src.gen_run --dry-run --clips 1` — exit 0, **zero** OpenRouter spend confirmed
   against `quota_usage`.
3. `python -m src.gen_run --clips 1` — real run. Expect: 4 stills sourced (record the ladder rung
   each **Shot** took), 4 image-to-video **Shots**, narration, assembly, an MP4 in
   `output/pending/`.
4. Reconcile spend: sum `quota_usage` for that `script_id` and confirm ≤ 150¢, and that the weekly
   rolling total is ≤ 800¢.
5. Confirm the `runs` row reached a terminal state with `success=1` and a populated summary.
6. Confirm the two historically abandoned runs (2026-06-22, 2026-07-18) were swept by Issue 60's
   finalizer on this run.
7. **Human review:** the user watches the MP4 and judges whether the image-first output is
   visibly better than the last Kling clip (`NPFJiqmd4ro`). `human_review` stays **true**, so
   nothing uploads until the user drags the file to `output/approved/`.
8. Only after the user approves: let the next scheduled `daily_upload` take it, and verify the
   AI-disclosure flag in Studio (INV-9).

If the render succeeds but the user judges quality insufficient, **do not iterate blindly** — file
a follow-up to revisit the model choice (the user chose to start on Seedance and revisit; Veo 3.1
Fast at $0.10/s and Kling v3.0 pro at $0.168/s are the documented alternatives).

## Invariants

- **INV-1 / INV-2** — Weekly ≤ 800¢, this **Clip** ≤ 150¢, both reconciled against `quota_usage`.
- **INV-4** — The run reaches a terminal state; the historical abandoned rows are swept.
- **INV-9** — The upload carries `containsSyntheticMedia=true` and the "Made with AI" footer.
- **INV-11** — The run completes within 90 minutes wall-clock.
- **INV-7** — Record which rung each **Shot** took; a licensed hit must not have been pre-empted by
  a **Generated still**.

## Acceptance criteria

- [ ] `bootstrap --check` passes.
- [ ] `--dry-run` exits 0 with zero spend.
- [ ] The live run produces a playable MP4 in `output/pending/` at 1080×1920.
- [ ] Per-**Shot** ladder rungs recorded in the ticket evidence.
- [ ] Spend for the `script_id` ≤ 150¢; weekly rolling total ≤ 800¢; both pasted as real query
      output, not asserted from memory.
- [ ] `runs` row terminal, `success=1`.
- [ ] Abandoned rows from 2026-06-22 and 2026-07-18 finalized.
- [ ] Wall-clock runtime recorded and ≤ 90 min.
- [ ] User has watched the MP4 and recorded a verdict.

## Blocked by

- Issues 59, 60, 61, 62 (WS1 — the pipeline must run and be observable), and 67 (image-first
  defaults must be live for this to test the new path).

## Verification-command

```
python -m src.bootstrap --check; if ($?) { python -m src.gen_run --dry-run --clips 1 }
```

The live `--clips 1` step and the human review are deliberately **outside** the automated gate —
they require spend authority and a human judgement, and must never run unattended in a loop.
