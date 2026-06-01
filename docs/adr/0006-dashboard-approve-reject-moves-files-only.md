# ADR-0006 — Dashboard approve/reject moves files only; the filesystem stays the HITL source of truth

**Status:** Accepted
**Date:** 2026-06-01
**Context:** Surfaced while grilling the dashboard **v2** redesign, which adds an in-UI
approve/reject action (`/grill-with-docs`; grill record
`CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`).

## Context

The human-in-the-loop sign-off gate is **filesystem-based, not in the DB.** A **Clip**
awaiting approval is simply an MP4 in `output/pending/`; the operator drags it to
`output/approved/`, and `daily_upload` uploads from `output/approved/` (while
`human_review` is on). `clips.status` only ever holds `cancelled | rejected_policy |
rejected_quality | uploaded` — there is **no** `pending`/`approved` status. The dashboard
v1 is read-only; v2 adds an Approve/Reject button. The button must write *something*, and
the tempting move is to introduce a DB status column for approval.

Approve is an outward-facing, hard-to-reverse act: an approved clip is published to YouTube
by `daily_upload` at its slot.

## Decision

**The dashboard's Approve/Reject action moves the file only — it never writes clip state to
the DB.** Approve performs `pending/ → approved/`; Reject performs `pending/ → rejected/`.
This is exactly the operation the manual drag-to-approve gate already performs, so
`daily_upload`'s contract is unchanged and the filesystem remains the single source of
truth.

Guardrails:
- The server re-scans and **acts only on a file currently in `output/pending/`**; it refuses
  if the clip is no longer there (stale UI state, already actioned).
- The move is **atomic** (`os.replace` within the same `output/` volume).
- **Reject is reversible** (move back `rejected/ → pending/`).
- The action is offered **only while `human_review` is on**; when off, `daily_upload` reads
  `pending/` directly and approval gates nothing, so the UI shows the queue read-only.

## Consequences

**Positive:**
- No new schema, no second source of truth, nothing to reconcile. The well-tested
  filesystem gate `daily_upload` already trusts is reused verbatim.
- The dashboard's safety story stays simple: every write is a constrained file move inside
  `output/`, never a DB mutation.

**Negative:**
- No DB audit trail of *who/when* approved (acceptable: single operator, localhost).
- Two write actors on `output/` (the operator/dashboard and `gen_run`); atomic `os.replace`
  plus the pending-only precondition make races benign on a single machine.

## Alternatives considered

1. **Write a DB `approved` status, leave the file in place.** Would force `daily_upload` to
   read DB state instead of the folder — changing the load-bearing gate's contract for no
   gain. Rejected.
2. **Move the file AND write a DB status.** Belt-and-suspenders audit, but creates two
   sources of truth that can disagree (file moved, DB write failed, or vice versa).
   Rejected: the reconciliation burden outweighs the audit value for a single-operator tool.

## References

- `docs/adr/0001` — two-gate sign-off for live uploads (the gate this action operates).
- `CONTEXT/CONTEXT.md` — **Review stage**, **Approve / Reject action**.
- Dashboard v1 PRD `docs/prds/web-review-calendar-dashboard.md` (read-only by construction;
  v2 is the deliberately-grilled write slice it anticipated).
- `src/dashboard/`, `src/daily_upload.py`, `config.yaml` (`paths.pending_dir`,
  `approved_dir`, `rejected_dir`, `human_review`).
