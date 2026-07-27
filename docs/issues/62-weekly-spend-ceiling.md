# Issue 62 — Weekly spend ceiling (800¢) + reconcile per-clip cap

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 1 (Urgent — the configured guardrail permits 7× the intended spend)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS1.

## What to build

Make the enforced ceiling match the stated budget.

`config.yaml` sets `ai_gen.daily_spend_cents_ceiling: 500` — that is **$5/day = $35/week**, seven
times the $8/week budget. **There is no weekly cap in the code at all.** Separately
`per_clip_cost_cents_max` has drifted: `config.yaml` says `300`, `progress.md` records `250`.

Scope:

- New config key `ai_gen.weekly_spend_cents_ceiling`, default **800**.
- `quota_ledger` gains a rolling-7-day OpenRouter total and a
  `quota_would_exceed_week(additional_cents)` predicate. "Rolling 7 days" means the 7×24 h window
  ending now, not a calendar week — a Sunday `gen_run` must see the previous Sunday's spend.
- `gen_run` checks the predicate **before** issuing each billable call (video *or* still). A call
  that would cross the ceiling is **refused, not attempted**: append a `spend_cap_reached` alert
  and finish the run `success=1` with a `capped` summary, so a budget stop reads as a normal
  outcome rather than a failure.
- Set `per_clip_cost_cents_max: 150` (D2: 5 **Clips**/week at ~88¢ leaves ~45% headroom) and
  remove the 300-vs-250 drift by making `config.yaml` the single source.
- `daily_spend_cents_ceiling` stays as a secondary burst guard; lower it to **300** so a single day
  cannot consume the whole week.

Note `quota_usage` records time in a **`recorded_at`** column (there is no `used_at` column) with a
separate `date` column — check the real schema before writing the window query.

## Invariants

- **INV-1** — Rolling 7-day OpenRouter spend ≤ 800¢. `gen_run` refuses to issue a billable call
  that would cross it, with a `spend_cap_reached` alert and a `capped` run summary — never a
  silent skip.
- **INV-2** — Cumulative spend per `script_id`, including retries, ≤ 150¢.
- **INV-3** — One **Generated still** ≤ 5¢; all stills for one **Clip** ≤ 20¢. (Enforcement lands
  with the still provider in Issue 64; define the config keys here.)

## Acceptance criteria

- [ ] `ai_gen.weekly_spend_cents_ceiling` (800), `per_clip_cost_cents_max` (150),
      `daily_spend_cents_ceiling` (300), and the INV-3 still keys all exist in `config.yaml` and
      the Pydantic config.
- [ ] `quota_would_exceed_week` uses a rolling 7×24 h window over `quota_usage.recorded_at`,
      filtered to `provider='openrouter'`.
- [ ] Spend at 799¢ + a 1¢ call → allowed. At 799¢ + a 2¢ call → refused.
- [ ] A refusal appends `spend_cap_reached`, finishes the run `success=1` with a `capped` summary,
      and issues **zero** provider calls (assert the call count).
- [ ] Spend recorded 8 days ago falls outside the window; spend 6 days ago falls inside.
- [ ] The existing per-clip cumulative cap (Issue 43) still passes — regression guard.
- [ ] Tests use a fake ledger and fake provider; no live billing.

## Blocked by

- None functionally, but land after Issue 60 to avoid colliding in the `gen_run` startup block.

## Verification-command

```
pytest tests/test_weekly_spend_ceiling.py tests/test_clip_spend_ceiling.py -q
```
