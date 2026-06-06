# Hermes director write contract

The **Hermes director** (Nous Research Hermes Agent on `nvidia/nemotron-3-ultra:free`)
authors **Directed scripts** in `data/state.db`. This document is the operator-facing
contract — the repo consume side is Issue 57 (`scripts.status='directed'` +
scripter narration-only branch).

## When to run

- Run **before** the Sunday 02:00 SGT `gen_run`.
- Do **not** acquire `data/.weekly_run.lock`.

## Topic selection

- Read `topics` where `status='unscripted'`.
- Pick on-niche Tech/AI stories per ADR-0004.
- After writing a **Directed script**, set `topics.status='scripted'` for that row.

## `scripts` row shape

Insert one row per directed topic:

| Field | Value |
|---|---|
| `script_id` | New UUID |
| `topic_id` | FK to the chosen topic |
| `title` | 5–8 word punchy Short title |
| `narration` | `''` (empty — qwen fills this later) |
| `shots_json` | JSON array of **4** tagged shots (hybrid schema below) |
| `style_suffix` | Channel style suffix from `config.yaml` / `CLAUDE.md` |
| `ollama_model` | `nvidia/nemotron-3-ultra:free` (director marker) |
| `created_at` | ISO UTC timestamp |
| `status` | **`directed`** |

## Tagged shot schema (`shots_json`)

Exactly four shots, alternating ~2 `real_image` + ~2 `ai_video`:

```json
{"kind": "real_image", "entity": "Apple M4 chip", "search_query": "optional", "duration_s": 4}
{"kind": "ai_video", "prompt": "soft blue data stream between glass panels", "duration_s": 4}
```

Rules (same as qwen scripter + ADR-0003):

- `real_image.entity` must be a product, logo, or object — **never a living person**.
- `ai_video.prompt` must not name real individuals.
- No living-individual depictions in any prompt.

## Downstream gates (no exemptions)

Directed shots pass the same pipeline as qwen-authored shots:

1. `normalize_shots`
2. `resolve_shot_plan` (licensed-only sourcing on the autonomous path)
3. Per-clip OpenRouter cost cap
4. `policy_gate` (banlist, profanity, NSFW, hook sanity, topic filter)

## Consume side (this repo)

1. `run_stage_b` selects `scripts.status='directed'`.
2. Qwen writes **narration only** from title + shots + topic summary.
3. Row flips to `status='pending'` and joins the normal render flow.

## Verification checklist

- [ ] Row has `status='directed'`, empty `narration`, valid tagged `shots_json`
- [ ] Topic claimed (`status='scripted'`)
- [ ] `ollama_model` marks the director backend
- [ ] After `gen_run`, narration filled and clip rendered with gates passed
