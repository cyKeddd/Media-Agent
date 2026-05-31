# Issue 39 — Backfill-gate the legacy unscripted backlog

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/steady-state-autonomous-cadence.md` — Steady-State Autonomous Cadence (M1).
Decisions of record: `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md` (S3),
`docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`.

## What to build

A backfill that applies the existing on-niche relevance gate to **Topics** that were
ingested *before* the gate shipped (2026-05-27) and are still sitting `unscripted`. 112 of
117 `unscripted` topics predate the gate and were never evaluated by it — the scripter
draws the highest-scored `unscripted` topic, so the next autonomous run keeps pulling
un-gated (and sometimes off-niche) topics. This is the root cause of the off-niche
reverse-aging clip — **not** a classifier bug, so the classifier prompt is unchanged.

A new deep module iterates `unscripted` topics and reuses the *same* keep/drop/fail-open
decision the live ingest gate uses (`_apply_niche_gate` / `classify_niche`):

- A real `off_niche` verdict → transition the topic to a terminal `rejected_off_niche`
  status (not deleted; auditable) so the scripter's selection query won't pick it.
- An `on_niche` verdict → leave it `unscripted` (kept).
- An `infrastructure_failed` verdict (Ollama down / invalid JSON) → leave it `unscripted`
  (fail-open) and count it as infra-skipped; it'll be re-evaluated on a later run.

Exposed as a CLI: `python -m src.topic_ingest.backfill [--dry-run]`. `--dry-run` reports
kept / rejected / infra-skipped counts with no DB writes. The run is idempotent and emits
a one-line summary plus per-rejection reason at debug level.

The classifier dependency is injectable so tests never touch Ollama or the network.

## Acceptance criteria

- [ ] New module exposes `backfill_unscripted_topics(cfg, repo, *, _classify=None, dry_run=False)`
      returning kept / rejected / infra-skipped counts.
- [ ] Off-niche `unscripted` topics are transitioned to a terminal `rejected_off_niche`
      status; the scripter's selection no longer picks them.
- [ ] On-niche topics remain `unscripted` (kept).
- [ ] `infrastructure_failed` topics remain `unscripted` (fail-open) and are counted
      separately — an Ollama outage never mass-rejects the queue.
- [ ] `--dry-run` writes nothing and prints the keep/reject/infra-skip preview.
- [ ] Re-running the backfill is a no-op for already-decided topics (idempotent).
- [ ] Genuinely on-niche legacy items (e.g. Gemini, GPT-5.5, OpenAI launches) survive a
      real backfill run; clearly off-niche items (business/IPO/culture) are rejected.
- [ ] Unit tests with an **injected fake classifier** cover: off_niche→rejected,
      on_niche→kept, infra_failed→kept+counted, dry_run→no writes, idempotency. No real
      classifier, Ollama, or network in any test.
- [ ] The classifier prompt is unchanged (data remediation only).

## Blocked by

None - can start immediately.
