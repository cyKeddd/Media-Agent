# Issue 57 — `directed` status + scripter narration-only branch + Hermes contract doc (ADR-0008)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/next-work-runs-retention-v3.1-hermes-director.md` — WS4. Decisions of record:
`docs/adr/0008-hermes-director-authors-scripts-rows.md`,
`CONTEXT/CONTEXT.md` (glossary: **Hermes director**, **Directed script**, **Topic**, **Shot**).

## What to build

The **consume side** of the **Hermes director** integration. The external **Hermes director**
inserts **Directed scripts** — `scripts` rows with `title` + tagged `shots_json` filled,
`narration=''`, `status='directed'` — and claims the **Topic**. This repo teaches the qwen
scripter to finish them by writing **narration only**, while leaving the full-qwen path intact
for **Topics** with no **Directed script**. (Configuring the Hermes Agent itself is Issue 58.)

End-to-end behavior:

- `scripts.status` gains the value `directed` (free-TEXT column; update the inline status
  comment in the schema). A **Directed script** is a row authored by the director:
  `title` + `shots_json` (the tagged hybrid schema `{kind, entity/prompt, duration_s,
  search_query}`) + `style_suffix` + `ollama_model` marked as the director model +
  `narration=''` + `status='directed'`.
- Repository: a `scripts_awaiting_narration()` query selecting `status='directed'`, and a helper
  to persist generated narration and flip the row to `pending`.
- The scripter generation stage gains a branch: pick up `status='directed'` rows and run the
  qwen narration generator in **narration-only** mode (prompted from the directed title + shots +
  topic summary), persist narration, set `status='pending'`. **Topics** with no **Directed
  script** use the existing full-generation path unchanged. Downstream (`gen_run` consuming
  `pending` scripts) is unchanged.
- Directed shots are **not** exempt from the channel's rules: they flow through the existing
  `normalize → resolve_shot_plan → per-clip cost cap → policy_gate` path, so licensed-only
  sourcing (ADR-0003) and the no-living-individuals rule still apply.
- Add a contract doc (`docs/hermes-director-contract.md`) specifying exactly what the Hermes
  operator must write: the tagged shot schema, `status='directed'`, claim the **Topic**
  (`topics.status='scripted'`), the model marker, and the downstream gates that still apply.

## Acceptance criteria

- [ ] `scripts.status` accepts `directed`; the schema status comment lists it.
- [ ] `scripts_awaiting_narration()` returns only `status='directed'` rows.
- [ ] The scripter branch generates narration for a `directed` row (using an injected/stubbed
      narration generator), persists it, and flips the row to `pending`; the row's `title` and
      `shots_json` are unchanged.
- [ ] A **Topic** with no **Directed script** still produces a full qwen-authored script.
- [ ] A directed row's shots still pass through normalize/resolve/cost-cap/policy unchanged
      (no director exemption).
- [ ] `docs/hermes-director-contract.md` exists and specifies the write contract (tagged shots,
      `status='directed'`, topic claim, model marker, downstream gates).
- [ ] Tests: `scripts_awaiting_narration` selection; the narration-only branch (directed →
      narration filled → `pending`); the full-qwen fallback for un-directed topics; shots
      unchanged. Stubbed narration generator (no live Ollama), as in the existing scripter tests.

## Blocked by

- None — can start immediately.
