# Steady-State Autonomous Cadence

**Status:** ready-for-agent
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-31
**Source session:** /grill-with-docs → /to-prd
**Decisions of record:** `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md`,
`docs/adr/0001-two-gate-signoff-for-live-uploads.md`,
`docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`
**Builds on:** `docs/prds/first-live-hybrid-gen-run.md` (Issues 35–38, done),
`docs/prds/finish-line-autonomous-hybrid.md` (Issue 29)

---

## Problem Statement

I have a working hybrid pipeline and my first **Hybrid clip** is uploaded
(`NPFJiqmd4ro`, publish Thu 2026-06-04 09:00 SGT). The north star is a
**fire-and-forget** loop: a weekly `gen_run` and a daily `daily_upload` that ship Hybrid
clips on a Tue/Thu cadence with no hand-holding. But I cannot flip that loop on today,
because four things are wrong or undecided:

1. **The topic queue is poisoned.** My off-niche reverse-aging clip wasn't a classifier
   bug — it was drawn from topic #69, fetched 2026-05-20, a week *before* the ADR-0004
   ingest relevance gate existed. **112 of 117 `unscripted` topics predate the gate** and
   were never evaluated by it. The scripter picks the highest-scored `unscripted` topic,
   so the next autonomous run keeps pulling un-gated topics. While `human_review` is on I
   catch these by hand (burning ~$2 of Kling each time on a $20/mo budget); the moment
   review turns off, off-niche clips **auto-publish silently**.
2. **The scheduled tasks would fail or run the wrong code.** `weekly_run.xml` still calls
   `-m src.weekly_run`, a module renamed to `gen_run` (the `gen_run_failed
   ModuleNotFoundError` entries in `logs/alerts.md` are exactly this). Worse, both
   scheduler XMLs point their `.venv` python at `C:\Users\cryptix\Documents\Media-Agent-main`
   — a stale second copy of the repo — not the live `Desktop\Work` tree I actually ship
   from. An unattended run today would either crash or run week-old code.
3. **I don't know the autonomous clip count is safe.** A weekly run must produce exactly
   **2 clips** (one Tue, one Thu = the budget), not more. I need that pinned and proven
   before I let it run with my card attached.
4. **I have no defined trigger for going hands-off.** "First 2 weeks of `human_review`"
   is a vague calendar phrase. I need a concrete, evidence-based rule for *when* the
   scheduler turns on and *when* `human_review` turns off, so the irreversible step
   (unattended auto-publish) only happens once the autonomous path has actually run clean.

## Solution

Make the loop safe to leave alone, then turn it on in a defined order. Concretely:

1. **Backfill-gate the legacy backlog.** Run the *existing* on-niche classifier over the
   `unscripted` topics and reject the off-niche ones to a terminal status, so the scripter
   can only ever draw a gated **Topic**. Keep genuinely on-niche legacy items (Gemini,
   GPT-5.5, OpenAI launches). Honor the same **fail-open-on-infrastructure-failure** rule
   the live gate uses — an Ollama hiccup must never mass-reject the queue. The classifier
   **prompt is unchanged**; this is a data remediation, not a tuning change. (The
   retired G3 "prompt retune" is the wrong fix — the new-ingest gate already rejects ~10
   off-niche items per run correctly.)
2. **Fix and re-register the scheduled tasks.** Point `weekly_run.xml` at
   `-m src.gen_run --clips 2` and repoint both XMLs' `.venv` python to the live
   `Desktop\Work\Media-Agent-main` tree. Re-register both Task Scheduler tasks.
3. **Pin the 2-clip count.** A regression test asserting the run caps selection to
   `--clips` (default 2); operator confirmation via `gen_run --dry-run` (zero spend) that
   a weekly run yields exactly 2 clips slotted Tue + Thu.
4. **Define the on/off triggers and follow the order.** Enable the scheduler only after
   the ship gate passes and the prereqs (top-up, backfill, XML re-register) are done; turn
   `human_review` off only on an **evidence + calendar-floor** rule.

The single real, billed `gen_run` is an **operator-run gate**, never automated and never
exercised by tests. Tests use injected fakes and dry-runs only — no real Kling, no
network, no spend.

## User Stories

### Niche backlog backfill (M1)

1. As the channel owner, I want the off-niche topics already sitting in my `unscripted`
   queue rejected, so that the scripter can never draw a topic that predates the relevance
   gate.
2. As the channel owner, I want the backfill to use the *same* on-niche classifier the
   live ingest gate uses, so that "on-niche" means exactly one thing across fresh and
   legacy topics.
3. As the channel owner, I want genuinely on-niche legacy topics (Gemini, GPT-5.5, OpenAI
   launches) **kept**, so that backfilling doesn't throw away good queued material.
4. As the channel owner, I want a topic the classifier can't evaluate due to
   infrastructure failure (Ollama down / invalid JSON) **kept** (fail-open) and counted
   separately, so that an outage never mass-rejects my queue.
5. As the channel owner, I want off-niche topics moved to a terminal status (e.g.
   `rejected_off_niche`), not deleted, so that the decision is auditable and reversible.
6. As the channel owner, I want a `--dry-run` mode that reports how many topics would be
   kept / rejected / infra-skipped without writing anything, so that I can preview the
   purge before committing.
7. As the channel owner, I want the backfill idempotent — re-running it changes nothing
   for already-decided topics — so that I can run it safely more than once.
8. As the channel owner, I want a one-line summary (kept N, rejected M, infra-skipped K)
   logged at the end, so that I have evidence of what the backfill did.
9. As the channel owner, I want each rejection's reason captured (the classifier's reason
   string) at debug level, so that I can spot-check the backfill's judgement.

### Scheduler fixes + re-registration (M2)

10. As the channel owner, I want the weekly scheduled task to run `-m src.gen_run`, not the
    renamed-away `src.weekly_run`, so that the unattended run stops dying with
    `ModuleNotFoundError`.
11. As the channel owner, I want the weekly task to pass `--clips 2` explicitly, so that
    the autonomous run's clip count is unambiguous and budget-bounded.
12. As the channel owner, I want both scheduler tasks to run the python in my live
    `Desktop\Work\Media-Agent-main` tree, not the stale `Documents\` copy, so that the
    scheduler runs the code I actually ship.
13. As the channel owner, I want both Task Scheduler tasks re-registered after the XML
    fixes, so that the corrections actually take effect.
14. As the channel owner, I want to confirm the weekly task's trigger is the intended day
    (Sunday) and the daily task's is daily 09:00 SGT, so that the cadence I configured runs.

### 2-clip count guard (M3)

15. As the channel owner, I want a test proving the run caps the number of generated clips
    to `--clips` (default 2), so that the weekly run can never silently generate 7 clips
    and blow the budget.
16. As the channel owner, I want a `gen_run --dry-run` to show exactly 2 selected scripts
    slotted onto a Tuesday and a Thursday, so that I can verify the cadence without spend.

### Enable + hands-off triggers (M4 — operator gate, no code)

17. As the channel owner, I want the autonomous scheduler enabled only after the
    `NPFJiqmd4ro` ship gate (T+1h, Thu 06-04) passes, so that I never automate an
    unverified pipeline.
18. As the channel owner, I want OpenRouter topped up to $20 before any autonomous run, so
    that an unattended `gen_run` doesn't abort mid-run on an empty balance.
19. As the channel owner, I want the backlog backfilled and the scheduler XMLs fixed before
    I enable the schedule, so that the first unattended run draws gated topics and runs the
    right code.
20. As the channel owner, I want the stability gate (T+48h, ~06-06) monitored in parallel
    rather than blocking enablement, so that forward work isn't stalled (per ADR-0001).
21. As the channel owner, I want `human_review` to stay ON after enablement, so that I
    still approve every clip during the confidence window.
22. As the channel owner, I want `human_review` flipped to false **only** when all of: the
    first-hybrid stability gate passed, **≥2 scheduler-driven weekly cycles** reviewed with
    zero off-niche/policy/quality rejections, **and ≥2 weeks** elapsed since the first
    hybrid ship (06-04), so that I go hands-off on evidence, not a calendar date.
23. As the channel owner, I want each autonomous cycle's review outcome recorded in
    `progress.md`, so that the "2 clean cycles" condition is auditable.

### Cadence + slot hygiene

24. As the channel owner, I want the hybrid clip publishing Thu 06-04 and the sample Tue
    06-02 (the duplicate-slot resolution), so that I have a clean one-clip-per-slot Tue+Thu
    week and an unambiguous two-gate subject.
25. As the channel owner, I want the first two autonomous clips to land on the Tue/Thu
    slots the allocator assigns, so that Slice 11's weekday cadence is confirmed in the
    autonomous path.

## Implementation Decisions

Locked in the grill record (S1–S7). Summary:

1. **M1 is a new deep module reusing the live gate's decision.** A function such as
   `backfill_unscripted_topics(cfg, repo, *, _classify=None, dry_run=False) -> BackfillResult`
   iterates `unscripted` **Topics**, applies the same keep/drop/fail-open logic as
   `_apply_niche_gate` (drop only on a real `off_niche`; keep on `on_niche` **and** on
   `infrastructure_failed`), and on a real off-niche verdict transitions the topic to a
   terminal status. `_classify` is injectable (defaults to `classify_niche`). Pure given
   the injected classifier and repo — no network in the unit. CLI:
   `python -m src.topic_ingest.backfill [--dry-run]`.
2. **Terminal status = `rejected_off_niche`.** A new `topics.status` value, distinct from
   `unscripted`/`scripted`, that the scripter's selection query does not pick up. Off-niche
   topics are **transitioned, not deleted**, so the decision is auditable. Infra-skipped
   topics stay `unscripted` (they'll be re-evaluated next run, fail-open).
3. **The classifier prompt is unchanged.** This task changes queue *data*, not the
   classifier. Scripter-framing drift (a borderline-AI topic framed as non-AI) is logged
   as a deferred scripter-quality follow-up, not addressed here.
4. **M2 is config + a deploy step, not application code.** `scripts/weekly_run.xml`:
   `Arguments` `-m src.weekly_run` → `-m src.gen_run --clips 2`; `Command` path
   `Documents\Media-Agent-main` → `Desktop\Work\Media-Agent-main`. `scripts/daily_upload.xml`:
   same `Command` path repoint. Re-register via `schtasks`/Task Scheduler. (If the two repo
   copies should be consolidated rather than just repointed, that's an operator call noted
   in Further Notes.)
5. **M3 is a regression test + a dry-run verification.** `--clips` already defaults to 2
   and caps selection via `selected[:clips_n]`; the test pins that invariant. The 2-clip,
   Tue+Thu verification is done with `gen_run --dry-run` (no DB writes, no spend).
6. **M4 is an operator acceptance gate with no code.** Enable order:
   ship-gate-pass → top-up $20 → backfill (M1) → XML fix + re-register (M2) → enable
   schedule. `human_review` off-trigger is the evidence + calendar-floor rule (story 22).
   Evidence recorded in `progress.md`, consistent with ADR-0001.
7. **No schema migration beyond the new `status` value, no new billed API calls, no
   uploader/disclosure changes.** Hybrid clips remain `content_kind='ai_generated'`;
   Slice 9 disclosure already applies.

## Testing Decisions

### What makes a good test here

Test external behavior at a module boundary with injected dependencies — never the
network, never Ollama, never Kling, never real spend. Assert *what the seam decides*
(keep/drop/fail-open, capped count), not how it's wired. This matches the existing
discipline in the Issue 31 niche-gate tests and `tests/test_hybrid_gen_run.py`
(patched-stage orchestration).

### Modules under test

| Module | Test asserts |
|--------|--------------|
| **M1** `backfill_unscripted_topics` | Inject a fake `classify`. A topic the fake calls `off_niche` → transitioned to `rejected_off_niche`; `on_niche` → left `unscripted`; `infrastructure_failed=True` → left `unscripted` (fail-open) and counted as infra-skipped. `dry_run=True` → counts returned, **no repo writes**. Idempotent: re-running over already-decided topics is a no-op. No real classifier, no network. |
| **M3** clip-count cap | With more than 2 selectable scripts, the run selects exactly `clips_n` (default 2). Assert against the selection seam with a fake repo / patched stages — **no Kling client constructed or called**, no render, no spend. |

### Explicitly not tested with spend

Per operator instruction: no test (or test fixture) calls the real video-generation path.
The only real, billed `gen_run` is the operator's M4 acceptance step. All automated
verification of the autonomous count/slotting uses `gen_run --dry-run`.

### Prior art

- Issue 31 niche-gate tests — M1 extends the same injected-`classify` pattern.
- `src/narration/aligner.py` CPU-fallback tests — the model for "distinguish
  infrastructure failure from a real negative result" (mirrors the fail-open rule).
- `tests/test_hybrid_gen_run.py` — patched-stage orchestration for the M3 count assertion.
- `tests/test_config_p4.py` — typed config validation, if any config field is touched.

## Out of Scope

- **Web review/calendar dashboard.** The explicit **next-up follow-on** — a local app to
  review/preview what's scheduled and see a calendar of upcoming publishes. Captured here
  so it isn't lost; it gets its own grill + PRD and is **not** built in this round.
- **Issue 29's actual gate execution** is referenced as the M4 trigger but its sign-off
  lives in Issue 29, not this PRD.
- **Retuning the niche classifier prompt** — retired as the wrong fix (the queue, not the
  prompt, was the problem).
- **Scripter content-quality grill** (hook strength, stat hallucination, framing drift).
- **Quota-increase audit / collapsing `daily_upload` into `gen_run`.**
- **Phase 8 stretch:** thumbnails, A/B titles, TikTok/Reels.
- **Kokoro install, CUDA cuBLAS PATH fix** (CPU-fallback alignment works today).
- **Consolidating the two repo copies** (`Documents\` vs `Desktop\Work\`) beyond repointing
  the scheduler — noted as an operator decision, not in scope.

## Further Notes

- **The dashboard is next.** After this steady-state path lands, the immediate follow-on is
  the local review/calendar dashboard: see what's in `output/pending/`, preview clips,
  view the `publish_at_utc` schedule as a calendar. It deserves its own grill because the
  central question — read-only viewer vs. an approval surface that *replaces* the
  filesystem drag-to-approve HITL gate — materially changes its architecture.
- **Why backfill instead of purge:** ~30+ of the 112 pre-gate topics are genuinely
  on-niche (Gemini, GPT-5.5, OpenAI launches); a wholesale purge would shrink the queue
  before autonomy. Backfill keeps the good ones.
- **Two repo copies exist** (`Documents\Media-Agent-main` and the live
  `Desktop\Work\Media-Agent-main`). This PRD repoints the scheduler to the live tree;
  whether to delete the stale copy entirely is an operator decision flagged for later.
- **The hands-off flip is the one irreversible step here.** Everything else (backfill,
  XML fixes, enabling the schedule) is contained by `human_review` staying ON. That's why
  the off-trigger is evidence-based, not a date.
- **Spend-safety follow-on (Issue 43).** After this PRD's scope, OpenRouter auto-top-up was
  enabled — removing the balance backstop. The existing per-clip cap is enforced per-attempt,
  so a retry after a post-billing failure can double-bill a clip (the 252¢ reverse-aging
  incident). Issue 43 specs a cumulative per-clip ceiling + shot-reuse-on-retry. Recommended
  before the hands-off flip (story 22), not a hard blocker while `human_review` is ON.
