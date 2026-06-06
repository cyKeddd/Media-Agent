# ADR-0008 — The Hermes director authors `scripts` rows directly; qwen fills narration

**Status:** Accepted
**Date:** 2026-06-06
**Context:** Surfaced while grilling the **Hermes director** integration
(`/grill-with-docs`, 2026-06-06 next-work backlog session).

## Context

The user installed the **Nous Research Hermes Agent** — a standalone self-improving agent
(persistent memory, skills, NL-cron automations, subagent delegation, `execute_code` Python
tool with SQLite access, OpenAI-compatible API server) routing to a free backend model
(**`nvidia/nemotron-3-ultra:free`**). The goal: have it act as a creative **director** for the
channel — ideation (concept/angle) + visual direction (the per-shot Kling prompts), the
"responses sent to Kling and how the video will turn out."

Today the **scripter** (Ollama `qwen2.5:3b-instruct`) authors the whole **Script** —
`{title, narration, shots_json, ...}` — into the `scripts` table from a **Topic**. The question
was where the director's output enters the pipeline: a side-file brief, a new `topics` column,
or directly as `scripts` rows.

## Decision

**The Hermes director writes `scripts` rows directly, partially filled, and the qwen scripter
completes the narration.** Concretely:

- Hermes reads queued **Topics** (`topics.status='unscripted'`) from `state.db` via its
  `execute_code` tool, and for chosen topics inserts a `scripts` row with: `title`, `shots_json`
  (the **tagged hybrid schema** `{kind: real_image|ai_video, entity/prompt, duration_s,
  search_query}` — *not* a free-form brief), `style_suffix`, `ollama_model` marked as the Hermes
  director model, `narration=''`, and **`status='directed'`** (a new value).
- Hermes atomically sets that **Topic**'s `status='scripted'` so the normal scripter does not
  re-process it.
- The qwen scripter stage gains a branch: pick up `status='directed'` rows → generate
  **narration only** (to fit the directed title + shots + topic summary) → set `status='pending'`.
  **Topics with no directed script fall back to the full-qwen path unchanged.**
- Directed shots flow through the existing `normalize_shots → resolve_shot_plan → per-clip cost
  cap → policy_gate` path untouched, so **licensed-only sourcing (ADR-0003)** and the
  **no-living-individuals rule** stay enforced downstream — the director gets no exemption.
- **Scheduling, not locking, prevents races:** Hermes runs on its own schedule *before* the
  Sunday `gen_run` (e.g. Saturday). It does not take `data/.weekly_run.lock`.

The Hermes-side setup (director persona via `SOUL.md`/skill, auto-loading `CLAUDE.md` +
`CONTEXT.md`, model pick) is operator configuration, **outside this repo**. The repo change
is the **consume side**: the `directed` status + the narration-only scripter branch.

## Consequences

**Positive:**
- A markedly stronger visual director (Nemotron 3 Ultra) shapes concept + Kling prompts while
  qwen keeps its tuned ~40-word/hook narration rubric. No paid spend (free model).
- No new contract artifact to reconcile — the director's output lives in the same `scripts`
  table the rest of the pipeline already reads.

**Negative:**
- An **external agent writes into `state.db`** — surprising to a future reader, and it couples
  Hermes to the `scripts` schema + the tagged-shot format. Schema drift can silently break it.
- A new `scripts.status='directed'` value the scripter state machine must handle; un-narrated
  rows are a transient state that retention/quality stages must ignore.
- Race-avoidance relies on **scheduling discipline** (Hermes before `gen_run`), not a lock.

## Alternatives considered

1. **File brief `data/director_briefs/{topic_id}.json`.** No migration, decoupled, matches the
   filesystem-as-interface ethos. Rejected by the user in favour of single-source-of-truth DB rows.
2. **New `topics.director_brief_json` column.** Transactional but still needs the scripter to
   merge brief→script. Rejected as more moving parts than direct rows.
3. **Hermes writes complete rows (narration too), no scripter branch.** Near-zero repo change,
   but drops qwen's narration rubric. Rejected: keep the writer/director split.

## References

- `CONTEXT/CONTEXT.md` — **Hermes director**, **Directed script**.
- [ADR-0003](0003-licensed-only-image-sourcing-for-autonomous-ships.md) (licensed-only sourcing — still enforced),
  [ADR-0004](0004-ai-centric-niche-and-ingest-relevance-gate.md) (niche gate).
- `src/scripter/`, `src/state/schema.sql` (`scripts.status`, `shots_json`),
  `src/gen_run.py` (shot → Kling assembly).
- Hermes Agent docs: https://hermes-agent.nousresearch.com/docs
