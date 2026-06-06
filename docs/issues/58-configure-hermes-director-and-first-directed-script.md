# Issue 58 — Configure the Hermes director + first Directed script end-to-end

**Status:** needs-operator (HITL)
**Type:** HITL

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS4. Decisions of record:
`docs/adr/0008-hermes-director-authors-scripts-rows.md`,
`CONTEXT/CONTEXT.md` (glossary: **Hermes director**, **Directed script**).

## What to build

The **operator-side** setup of the **Hermes director** and a first end-to-end verification. This
is **not** a Composer/AFK task — it is configuration of the external Nous Research Hermes Agent
(done by the operator with assistant help) plus a live check that one **Directed script** flows
through the consume side (Issue 57). No repo code beyond what Issue 57 ships.

End-to-end behavior:

- Finish the Hermes Agent install and select the `nvidia/nemotron-3-ultra:free` backend model.
- Give Hermes a **director persona** (`SOUL.md` and/or a skill) and ensure it auto-loads the
  channel context (`CLAUDE.md`, `CONTEXT/CONTEXT.md`).
- Author the director routine (using Hermes's `execute_code`/SQLite access) that reads queued
  **Topics**, produces a concept + tagged directed shots, and writes a **Directed script** per
  the `docs/hermes-director-contract.md` contract — inserting the `scripts` row
  (`status='directed'`, `narration=''`) and claiming the **Topic** (`topics.status='scripted'`).
- Schedule Hermes to run **before** the Sunday `gen_run` (it does not take the run lock).
- Verify one **Directed script** end-to-end: the qwen scripter fills narration → `pending` →
  `gen_run` renders it → the directed shots passed licensed/cost/policy gates.

## Acceptance criteria

- [ ] Hermes Agent runs on `nvidia/nemotron-3-ultra:free` with a director persona and the
      project context loaded.
- [ ] Hermes writes a conformant **Directed script** (matches `docs/hermes-director-contract.md`)
      and claims its **Topic**.
- [ ] The qwen scripter picks the directed row up, fills narration, and flips it to `pending`.
- [ ] A `gen_run` renders the directed **Clip**; directed shots cleared the licensed-sourcing,
      cost-cap, and policy gates; no living-individual prompts.
- [ ] Hermes is scheduled ahead of the Sunday `gen_run` and does not contend for
      `data/.weekly_run.lock`.
- [ ] Outcome recorded in `progress.md` / the session handoff.

## Blocked by

- Issue 57 — `directed` status + scripter narration-only branch + Hermes contract doc (the
  consume side and the contract this configuration targets).
