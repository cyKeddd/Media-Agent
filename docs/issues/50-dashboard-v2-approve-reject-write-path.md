# Issue 50 — Dashboard v2 approve/reject write path

**Status:** complete
**Type:** AFK

## Parent

`docs/prds/dashboard-v2-health-first-redesign.md` — Dashboard v2 (health-first redesign +
approve/reject). Decisions of record: `CONTEXT/Grilling/2026-06-01-dashboard-v2-redesign.md`
(D2, D6, D7), `docs/adr/0006-dashboard-approve-reject-moves-files-only.md`,
`CONTEXT/CONTEXT.md` (glossary: **Approve / Reject action**, **Review stage**).

## What to build

The in-UI **Approve / Reject action** — the first and only write path the dashboard gains.
It *is* the existing drag-to-approve gate performed via the UI, and it **moves the file only**
(ADR-0006): it never writes clip state to the DB, so `daily_upload`'s contract is unchanged.

End-to-end behavior:

- A **review-action module** — `apply_review_action(clip_id, action, …)` over an injected
  output scanner + the configured pending/approved/rejected dirs — performs: **approve**
  → move `pending/ → approved/`; **reject** → move `pending/ → rejected/`; **unreject**
  → move `rejected/ → pending/`. It re-scans and **acts only on a file currently in
  `pending/`** (for approve/reject), returning a refused/no-op result otherwise, and performs
  an **atomic** `os.replace` within the `output/` volume. No DB write, no billed call.
- **POST endpoints** (approve / reject) delegate to the module and return the action result;
  the page re-fetches `/api/view` after a successful action so the clip leaves the queue and
  health/counts update.
- The controls are **gated on `human_review`** read from config: when **on**, review-queue
  cards show **Approve / Reject** buttons with a **confirm step**; when **off**, the action
  endpoints refuse and the queue renders **read-only with an "autonomous mode — approval
  disabled" banner**.
- Every write is a constrained file move strictly inside `output/`; nothing else on disk is
  touched and the DB is never mutated.

## Acceptance criteria

- [ ] Review-action module: approve moves pending→approved; reject moves pending→rejected;
      unreject moves rejected→pending; a clip **not** in `pending/` → refused/no-op (no move);
      move is atomic (`os.replace`); the DB is never written.
- [ ] POST approve/reject endpoints delegate to the module and return its result; the page
      re-fetches after a successful action (clip leaves the queue, counts update).
- [ ] A confirm step is required in the UI before an action takes effect.
- [ ] When `human_review` is **on**, the buttons appear; when **off**, the action endpoints
      refuse and the queue is read-only with the autonomous-mode banner.
- [ ] No write occurs outside `output/`; no DB mutation; no pipeline/billed call.
- [ ] `daily_upload`'s behavior is unchanged (still reads `output/approved/`).
- [ ] Tests: **M4** review-action module against a temp pending/approved/rejected tree
      (approve/reject/unreject moves, pending-only precondition refusal, atomicity, no DB
      write); **M5** `TestClient` smoke (POST approve moves the file in a temp tree and returns
      the result; with `human_review` off the action endpoint refuses; MP4 path guard intact).
      No real DB/server/network; no billed code.

## Blocked by

- Issue 49 — Dashboard v2 work-area panels restyled (provides the restyled review-queue cards
  that host the Approve / Reject controls).
