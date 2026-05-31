# Issue 43 — Cumulative per-clip spend ceiling (retry-safe)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/steady-state-autonomous-cadence.md` — Steady-State Autonomous Cadence
(spend-safety hardening; follow-on raised 2026-05-31 after enabling OpenRouter
auto-top-up). Decisions of record: `CONTEXT/Grilling/2026-05-31-steady-state-autonomy.md`
(S7), memory `openrouter-spend-guardrails`.

## What to build

A per-clip spend ceiling that holds **across retries**, so a single **Clip** can never
bill more than `per_clip_cost_cents_max` (250¢ = 2.5 credits) over its whole lifetime —
not just within one attempt.

**The gap today.** `per_clip_cost_cents_max` is enforced two ways in `_generate_clip`, and
neither survives a retry:

1. A **pre-billing projection** (`billable_ai * 67 > cap`) — checked once, before any
   Kling call.
2. A **post-billing actual delta** — `clip_cost = quota_today_total(after) −
   quota_today_total(before)`, where `before` is read at the *start of the current
   attempt*.

When a clip fails **after** Kling has billed — e.g. narration/align/assemble error (the
2026-05-31 reverse-aging clip failed on a `pitch` config bug) — the retry re-enters
`_generate_clip` with a **fresh `before` baseline**. The prior attempt's spend is folded
into the baseline, so the retry only measures its own delta (126¢ ≤ 250¢, passes). Two
attempts = **252¢ on one clip**, and neither check trips. `quota_usage` is keyed only by
`(date, endpoint, units)` — there is no clip/script attribution, so lifetime per-clip
spend cannot be summed.

With **auto-top-up ON**, a low balance no longer acts as a circuit-breaker, so this
config cap is now the *only* backstop against retry double-billing.

**Two-part fix:**

1. **Attribute every OpenRouter charge to its Clip and enforce cumulatively.** Each Kling
   charge is recorded against its `clip_id` / `script_id`. The per-clip cap is checked
   against the **cumulative sum for that clip across all attempts** — a charge that would
   push the clip's lifetime spend over `per_clip_cost_cents_max` is refused *before* the
   call. The `daily_spend_cents_ceiling` (500¢) check is unchanged.
2. **Reuse already-billed Shots on retry; never re-bill.** A clip retried after a
   *post-billing* failure (narration / align / assemble) must reuse the already-succeeded
   `generation_jobs` **Shots** instead of regenerating them — mirroring
   `render_from_script --reuse-shots/--order`. Re-paying for a Shot already rendered is
   the actual waste; eliminating it makes the cumulative ceiling rarely bind in practice.

Schema: add a nullable clip/script reference to the spend record (or a per-clip spend
tally) so cumulative per-clip cost is queryable. No new billed API calls. No uploader or
disclosure changes.

## Acceptance criteria

- [ ] Each OpenRouter (Kling) charge is attributed to a `clip_id` / `script_id` and is
      queryable as a cumulative per-clip total.
- [ ] A charge that would push a clip's **lifetime** spend over `per_clip_cost_cents_max`
      (250¢) is refused before the call — enforced on the cumulative total, not a
      single-attempt delta.
- [ ] A clip retried after a post-billing failure **reuses** already-succeeded
      `generation_jobs` Shots and bills **0¢** more for those Shots (no regeneration).
- [ ] The `daily_spend_cents_ceiling` (500¢) behavior is unchanged.
- [ ] Re-running the 2026-05-31 scenario (Kling bills 126¢ → assembly fails → retry) ends
      at **126¢ total for that clip**, not 252¢.
- [ ] Unit tests with a **fake spend ledger / fake Kling client** cover: cumulative cap
      refusal across two attempts; retry reuses shots and bills nothing further; daily
      ceiling still trips independently. **No real Kling, no network, no spend** in any
      test; dry-run safe.
- [ ] `per_clip_cost_cents_max: 250` and `daily_spend_cents_ceiling: 500` remain unchanged
      in config (do not raise the caps).

## Blocked by

None - can start immediately. (Recommended to land before Issue 42 flips `human_review`
off, since auto-top-up removes the balance backstop during unattended runs — but not a
hard blocker, as `human_review` keeps a human in the loop until then.)
