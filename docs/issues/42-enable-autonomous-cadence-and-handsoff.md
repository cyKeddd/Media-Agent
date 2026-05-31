# Issue 42 — Enable autonomous cadence + hands-off sequencing

**Status:** ready-for-agent
**Type:** HITL (operator gate, no code)

## Parent

`docs/prds/steady-state-autonomous-cadence.md` — Steady-State Autonomous Cadence (M4).
Decisions of record: `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md` (S4, S5, S7),
`docs/adr/0001-two-gate-signoff-for-live-uploads.md`.

## What to build

The operator acceptance gate that turns the loop on, in a defined order, and the rule for
going hands-off. No application code — this is sequencing + evidence, recorded in
`progress.md` per ADR-0001.

**Enable order (each prereq done before the next):**

1. `NPFJiqmd4ro` **ship gate (T+1h, Thu 2026-06-04)** passes (Issue 29).
2. **OpenRouter funded** — auto-top-up is ON (enabled 2026-05-31, initial $20), so balance
   is no longer a spend backstop. The `config.yaml` caps are now the sole guardrail:
   `per_clip_cost_cents_max: 250` (hard 2.5 credits/video) and `daily_spend_cents_ceiling: 500`,
   both unchanged. Guard against retry double-billing on a single clip.
3. **Backlog backfilled** (Issue 39 run over the real DB; off-niche legacy topics
   rejected).
4. **Scheduler XMLs fixed + re-registered** (Issue 40).
5. **Enable the weekly schedule.** `human_review` stays ON — every clip is still
   operator-approved. The **stability gate (T+48h, ~06-06)** is monitored in parallel and
   does not block enablement.

**Hands-off trigger — flip `human_review` true → false only when ALL of:**

- (a) the first-hybrid **stability gate passed**, AND
- (b) **≥2 scheduler-driven weekly `gen_run` cycles** have been reviewed with **zero**
  off-niche / policy / quality rejections, AND
- (c) **≥2 weeks** elapsed since the first hybrid ship (2026-06-04) — a floor, not the
  trigger.

The first two autonomous clips must land on the Tue/Thu slots the allocator assigns
(Slice 11 confirmed in the autonomous path).

**Recommended before the hands-off flip:** Issue 43 (cumulative per-clip spend ceiling).
With auto-top-up ON the balance is no longer a backstop, so a retry double-bill could
exceed 250¢/clip unattended. Not a hard blocker (human_review keeps a human in the loop
until the flip), but it should land before `human_review` goes false.

## Acceptance criteria

- [ ] Ship gate on `NPFJiqmd4ro` recorded passed before the schedule is enabled.
- [x] OpenRouter funded — auto-top-up ON (2026-05-31). Caps are the sole backstop:
      `per_clip_cost_cents_max: 250` + `daily_spend_cents_ceiling: 500` confirmed unchanged;
      do not raise without approval.
- [ ] Issue 39 backfill run over the real DB; off-niche legacy topics rejected (evidence
      in `progress.md`).
- [ ] Issue 40 scheduler tasks fixed + re-registered.
- [ ] `gen_run --dry-run` confirms exactly 2 scripts slotted Tue + Thu (zero spend) before
      the live schedule is trusted.
- [ ] Weekly schedule enabled with `human_review` still ON.
- [ ] Stability gate (T+48h) outcome recorded; monitored in parallel, not blocking.
- [ ] Each scheduler-driven cycle's review outcome recorded in `progress.md` toward the
      "≥2 clean cycles" condition.
- [ ] `human_review` flipped to false **only** after all of (a)+(b)+(c) are met, with the
      evidence recorded.

## Blocked by

- Issue 39 (backfill-gate the legacy backlog)
- Issue 40 (fix + re-register scheduler tasks)
- Issue 41 (pin the weekly 2-clip count)
- Issue 29 (first hybrid ship — ship gate is enable prereq #1)
