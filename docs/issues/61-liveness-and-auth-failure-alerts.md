# Issue 61 — Liveness alert + fail-fast on OpenRouter auth errors

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 1 (Urgent — this is the signal that would have caught the outage in week one)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS1.

## What to build

Two signals the pipeline is missing.

**1. Liveness.** `logs/alerts.md` has not been written since 2026-06-07. Every `generation` run
since reported `success=true` with `generate_clips=0` — a run that produces nothing currently
looks identical to a healthy one. Add: on either entry point's startup, if no `clips` row has been
rendered in the last `liveness_stale_days` (new config key, default **7**), append an alert of
kind `liveness_stalled` stating the days elapsed and the last rendered **Clip**.

The alert fires at most once per day, so a long stall produces a daily heartbeat rather than one
alert per invocation.

**2. Fail-fast on auth.** An OpenRouter `401`/`403` currently flows into the generic retry path.
That is exactly wrong: an invalid key will never succeed on retry, and burning the retry budget
obscures the cause. Per INV-12, a `401`/`403` from OpenRouter must **abort the run immediately**
with an alert of kind `auth_failed`, distinct from the transient-failure path, and must not be
retried.

Transient conditions (5xx, timeouts, connection errors) keep the existing tenacity retry ×3 with
backoff.

## Invariants

- **INV-5** — If no **Clip** has been rendered in 7 days, an alert of kind `liveness_stalled` is
  appended on the next run of either entry point.
- **INV-12** — OpenRouter `401`/`403` aborts the run immediately with an `auth_failed` alert and no
  retry loop. 5xx/timeout retries ×3 with backoff.
- **INV-6** — The `auth_failed` alert must not contain the key value.

## Acceptance criteria

- [ ] New config keys `liveness_stale_days` (default 7) and the alert kinds `liveness_stalled` /
      `auth_failed` documented alongside the existing kinds.
- [ ] No **Clip** rendered in > `liveness_stale_days` → `liveness_stalled` alert appended, naming
      the elapsed days and the last rendered clip.
- [ ] A **Clip** rendered within the window → no alert.
- [ ] The liveness alert is emitted at most once per calendar day.
- [ ] A stubbed OpenRouter `401` aborts the run, appends `auth_failed`, and makes **exactly one**
      HTTP attempt (assert the call count — no retries).
- [ ] A stubbed `403` behaves identically to `401`.
- [ ] A stubbed `503` still retries per the existing policy (regression guard).
- [ ] No alert text contains a full API key.
- [ ] Tests use a fake HTTP layer — no live OpenRouter calls.

## Blocked by

- Issue 59 (key loading), Issue 60 (shares the entry-point startup path — land 60 first to avoid
  two agents editing the same startup block).

## Verification-command

```
pytest tests/test_liveness_alerts.py tests/test_openrouter_auth_failfast.py -q
```
