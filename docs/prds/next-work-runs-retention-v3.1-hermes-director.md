# Next-work backlog — daily Run health, output hygiene, dashboard v3.1 controls, Hermes director

**Status:** ready-for-agent
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-06-06
**Source session:** /grill-with-docs → /to-prd (2026-06-06 next-work backlog)
**Decisions of record:**
`docs/adr/0007-dashboard-may-mutate-prepublication-fields.md`,
`docs/adr/0008-hermes-director-authors-scripts-rows.md`,
`CONTEXT/CONTEXT.md` (glossary: **Run**, **Pipeline health**, **Review stage**,
**Approve / Reject action**, **Operator override**, **Hermes director**, **Directed script**)
**Builds on:** `docs/prds/dashboard-v2-health-first-redesign.md` (complete; Issues 47–50),
`docs/adr/0005`, `docs/adr/0006`

---

## Problem Statement

Four unrelated rough edges remain after dashboard v2 shipped, and I want them cleared in one
pass so the agent is genuinely hands-off and the dashboard earns its keep as a console:

1. **The daily health tile lies by omission.** The dashboard reads the `runs` table to show
   whether the weekly **Run** and the daily **Run** are healthy. `gen_run` writes its `runs`
   row, but `daily_upload` never does — it only appends to `logs/runs.md`. So the daily tile
   reads "Not yet run" forever even after `daily_upload` has fired successfully, and I can't
   trust the health band's daily half.

2. **Uploaded clips leave orphan files behind.** I found two MP4s sitting in `output/pending/`
   that are *also* in `output/approved/`, for **Clips** that are already published on YouTube.
   The dashboard correctly shows them as Published (not in the review queue), so this isn't a
   dashboard bug — but the duplicate pending copies are orphans no DB row points to, and
   retention's post-upload sweep only deletes the single `output_path` file, so they never get
   cleaned. The dashboard also re-derives a filename slug to locate a **Clip**'s file instead of
   trusting `output_path` like the rest of the pipeline does — a latent matching fragility.

3. **The dashboard is read + approve/reject only; I can't fix anything from it.** When a **Clip**
   is in the wrong slot or has a weak title, I have to leave the dashboard and edit the DB +
   rename files by hand. I want to reschedule a slot and edit a title from the UI, and I want to
   see when the next scheduled Run fires.

4. **My scripts' visuals are mediocre and I want a director.** I installed the Nous Research
   **Hermes Agent** and want it to act as a creative **Hermes director** — generating the video
   concept and the per-**Shot** Kling prompts (the "responses sent to Kling") with a far stronger
   model than the local qwen scripter, while qwen keeps writing the narration it's tuned for.

## Solution

Four independent workstreams, shippable in any order:

**WS1 — daily Run health.** `daily_upload` writes a SQLite `runs` row (`kind='daily'`) the same
way `gen_run` does: `start_run` at the top of the run, `finish_run` on every exit path, wrapped
so an unexpected crash still finalizes the row as failed. The row is written **only on real
runs** — `--dry-run` skips it, so a manual dry-run never masquerades as the latest daily health
on the dashboard (the existing `runs.md` append keeps its dry-run line). The `summary_json`
carries the shape the dashboard already reads (`uploaded`, `message`). The daily health tile
then populates on its own.

**WS2 — output hygiene + match hardening.** Retention's post-upload sweep finds **all** `output/`
copies of an uploaded **Clip** (by basename across `pending/`, `approved/`), not just the one in
`output_path`, so orphan duplicates get cleaned under the same `output_post_upload` TTL. The
dashboard locates a **Clip**'s file by `output_path` basename (the single source of truth, like
`daily_upload` and `slot_planner`) with the slug match kept only as a fallback. The two existing
orphans are cleaned once.

**WS3 — dashboard v3.1 Operator overrides + next-run countdown.** Three localhost-only controls:
a **next-run countdown** (read-only, from the Windows Task Scheduler next-run time / the
configured schedule); **reschedule slot** and **edit title** — the first **Operator overrides**
(ADR-0007), which *do* write the DB and rename the file, but only for a non-published **Clip**,
only while holding `data/.weekly_run.lock` (else `409`), DB-first-then-rename. Reschedule is a
free-form future datetime (snapped, padded `> now + 20 min`) with a collision *warning*; edit
title sets `suggested_title` **and** `hook` so it deterministically becomes the published title,
and renames the file's slug. Triggering `gen_run` and LAN/token auth stay deferred to **v3.2**.

**WS4 — Hermes director consume side (ADR-0008).** The **Hermes director** (external, configured
by the operator, on `nvidia/nemotron-3-ultra:free`) inserts **Directed scripts** — `scripts` rows
with `title` + tagged `shots_json` filled, `narration=''`, `status='directed'` — and claims the
**Topic**. This repo builds the *consume* side: the qwen scripter gains a branch that picks up
`status='directed'` rows and generates **narration only**, then sets `status='pending'`; topics
with no **Directed script** use the full-qwen path unchanged. Directed shots flow through the
existing `normalize → resolve_shot_plan → cost-cap → policy_gate` path, so licensed-only sourcing
(ADR-0003) and the no-living-individuals rule stay enforced. A short contract doc tells the
Hermes operator exactly what to write.

## User Stories

### WS1 — daily Run health

1. As the channel owner, I want `daily_upload` to record a `runs` row when it runs, so that the
   dashboard's daily health tile reflects reality instead of "Not yet run".
2. As the channel owner, I want a successful daily Run to show how many **Clips** it uploaded
   (`uploaded=N`), so that I can confirm today's publishing at a glance.
3. As the channel owner, I want a daily Run that found nothing to upload to show `no_candidates`,
   so that I can tell "ran, nothing to do" apart from "didn't run".
4. As the channel owner, I want a daily Run that aborts on an orphan-reconcile or crashes to show
   **Failed** with the error, so that the health band turns red when uploading is broken.
5. As the channel owner, I want a daily Run that is still mid-flight (e.g. OAuth hanging) to show
   **In progress**, so that a stuck upload is visible rather than invisible.
6. As the channel owner, I want `daily_upload --dry-run` to **not** write a `runs` row, so that my
   manual dry-runs never overwrite the dashboard's notion of the latest real daily Run.
7. As a developer, I want the daily Run summary to use the same JSON shape the dashboard view-model
   already reads, so that no dashboard change is needed to display it.
8. As a developer, I want the stale `runs.kind` schema comment corrected to `generation|daily`, so
   that the comment matches what the code actually writes.

### WS2 — output hygiene + match hardening

9. As the channel owner, I want orphaned MP4 copies of already-uploaded **Clips** cleaned up
   automatically, so that `output/pending/` and `output/approved/` don't accumulate stale files.
10. As the channel owner, I want retention to remove **every** `output/` copy of an uploaded
    **Clip** (not just the one in `output_path`), so that a duplicate left in another subdir is
    not stranded forever.
11. As the channel owner, I want the existing two orphan files cleaned once as part of this work,
    so that the tree starts clean.
12. As a developer, I want the dashboard to locate a **Clip**'s file by `output_path` basename
    (with slug as a fallback), so that the **Review stage** derivation no longer depends on
    re-deriving a slug that can drift from the filename.
13. As the channel owner, I want a **Clip** whose file moved between subdirs to still resolve to
    wherever the file actually is, so that the derived **Review stage** stays correct.
14. As a developer, I want the orphan sweep to respect the same `output_post_upload` TTL as the
    existing sweep, so that nothing is deleted earlier than today's policy allows.

### WS3 — dashboard v3.1 Operator overrides + next-run countdown

15. As the channel owner, I want the dashboard to show when the next scheduled generation and
    daily **Run** will fire, so that I know how long until the agent next acts.
16. As the channel owner, I want a live countdown to the next Run, so that I can decide whether to
    wait or trigger work manually later.
17. As the channel owner, I want to reschedule a non-published **Clip**'s slot from the UI, so that
    I can fix a bad or colliding slot without editing the DB by hand.
18. As the channel owner, I want to pick a free-form future date/time when rescheduling (snapped to
    :00/:30, at least 20 minutes out), so that the new slot is valid for `daily_upload`.
19. As the channel owner, I want a warning (not a hard block) if another non-published **Clip**
    already holds the slot I pick, so that I'm informed but not prevented from doubling up a day.
20. As the channel owner, I want to edit a non-published **Clip**'s title from the UI and have it
    become the actual published YouTube title, so that what I type is what viewers see.
21. As the channel owner, I want editing the title to also rename the file's slug, so that the file
    on disk stays human-readable and consistent with the title.
22. As the channel owner, I want every **Operator override** refused on a **Clip** that's already
    published (`youtube_video_id` set), so that I can't pretend to change something that lives on
    YouTube now.
23. As the channel owner, I want an **Operator override** to refuse (with a clear message) if a
    pipeline Run is in progress, so that my edit never races a live `gen_run`/`daily_upload`.
24. As a developer, I want overrides to write the DB first then rename the file, so that a crash
    between the two is healed by the existing `reconcile_slot_renames`.
25. As the channel owner, I want these controls only on `127.0.0.1`, so that nothing mutating is
    reachable from the LAN in this slice.
26. As the channel owner, I want the override buttons gated the same way approve/reject is, so that
    the control surface is coherent.

### WS4 — Hermes director consume side

27. As the channel owner, I want a **Hermes director** to author the concept + Kling shot prompts
    for chosen **Topics**, so that my **Clips** look directed rather than generic.
28. As the channel owner, I want the qwen scripter to write narration for a **Directed script**, so
    that I keep qwen's tuned ~40-word, hook-first narration over the director's visuals.
29. As the channel owner, I want **Topics** with no **Directed script** to keep generating via the
    full-qwen path, so that the pipeline still works when the director hasn't run.
30. As a developer, I want a `scripts.status='directed'` state for director-authored,
    narration-less rows, so that the scripter can tell them apart from finished scripts.
31. As a developer, I want the scripter to select `status='directed'` rows and generate narration
    only (then set `status='pending'`), so that **Directed scripts** join the normal render flow.
32. As a developer, I want the **Hermes director** to claim its **Topic** (set `status='scripted'`)
    when it writes a **Directed script**, so that the normal scripter doesn't double-process it.
33. As the channel owner, I want directed shots to pass the same licensed-sourcing, cost-cap and
    policy gates as qwen shots, so that the director gets no exemption from the channel's rules.
34. As a developer, I want a short contract doc specifying exactly what the Hermes operator must
    write (tagged shots schema, `status='directed'`, topic claim, model marker), so that the
    external agent and this repo agree without reading each other's code.
35. As the channel owner, I want the **Hermes director** to run before the Sunday `gen_run` and not
    take the run lock, so that scheduling discipline — not coupling — keeps them from racing.

## Implementation Decisions

### WS1 — daily Run health
- Add a pure `build_daily_run_summary(results) -> dict` mapping upload outcomes to
  `{"uploaded": <count of successful inserts>, ...}`; for the empty/no-candidate and
  orphan-abort paths produce `{"message": "no_candidates"}` and `{"error": "..."}` respectively.
  Shape is dictated by the existing `view_model._run_success_detail` (`uploaded`, `message`) and
  `run_reader._parse_summary` (top-level `error` → Failed tile).
- In `run_today`: when **not** dry-run, call `repo.start_run("daily")` once at the top; call
  `repo.finish_run(run_id, success, json.dumps(summary))` on every exit (orphan abort →
  `success=False`; no-candidates → `success=True`; normal completion → `success=True`; quota-break
  still completes the row). Wrap the body so an unexpected exception finalizes the row
  `success=False` with `{"error": ...}` then re-raises — mirroring `gen_run`.
- `--dry-run` writes **no** `runs` row. The existing `_emit_runs_row` → `runs.md` append is kept
  for both modes.
- Correct the `runs.kind` comment in `schema.sql` from `weekly|daily|bootstrap` to
  `generation|daily`.

### WS2 — output hygiene + match hardening
- Broaden `retention/cleanup.py::list_output_post_upload_candidates`: for each `clips` row with
  `status='uploaded'` and `updated_at <=` the TTL threshold, derive the **basename** from
  `output_path` and collect that basename wherever it exists across `pending/` and `approved/`
  (not only the directory named in `output_path`). Existing `_safe_unlink` (under-root guard) and
  the `output_post_upload` threshold are reused. `rejected/` keeps its own mtime TTL, untouched.
- `dashboard/scanner.py`: add a `by_basename: dict[str, tuple[str, Path]]` index to `ScanResult`
  (subdir rank breaks ties, same as `by_slug`).
- `dashboard/view_model.py::_resolve_location`: match order becomes
  `by_clip_id` → **`by_basename[Path(output_path).name]`** → `by_slug` (fallback). Subdir always
  comes from where the file actually sits on disk, so the derived **Review stage** is unaffected
  by a stale `output_path` directory.
- One-time cleanup of the two known orphans (`2026-06-02__slot_0900__genetic_leap_reverse_aging_51fa.mp4`
  and `…google_just_open_sourced…ac07.mp4` in `output/pending/`) — a small one-shot script or
  documented manual deletion; both **Clips** are already published.

### WS3 — dashboard v3.1 (ADR-0007)
- New pure `next_run` module: given the configured schedule (weekly Sun 02:00 SGT, daily 09:00
  SGT — from the Task Scheduler XMLs / config) and `now`, compute the next fire datetime per kind.
  View-model gains a `next_run` field per kind; the static UI renders a countdown (JS-side ticking
  off the served timestamps; no new poll).
- New deep `clip_mutation` module (sibling to `review_action.py`): pure core
  `plan_reschedule(clip_row, new_dt, tz, now) -> MutationPlan | Refusal` and
  `plan_edit_title(clip_row, new_title, clip_id) -> MutationPlan | Refusal`. A `MutationPlan`
  carries the DB field updates (`publish_at_utc`/`publish_slot_local`, or
  `suggested_title`/`hook`/`title_slug`) and the rename `(from_path, to_path)`. Refusals: clip is
  published, datetime not in the future+pad, etc. Rename targets reuse `slot_planner`'s
  `_build_new_filename` and `editor/slug.py::title_slug`.
- App layer: `POST /api/clip/{clip_id}/reschedule` and `POST /api/clip/{clip_id}/edit-title`.
  Each acquires `data/.weekly_run.lock` non-blocking (→ `409` if held), applies the plan
  **DB-first then `os.replace`**, returns a result mirroring `_action_response`. Collision on
  reschedule is surfaced as a warning field, not a refusal. Gated by `_require_human_review` like
  the existing actions.
- Reschedule datetime: tz-aware `Asia/Singapore`, snapped to :00/:30, validated `> now + 20 min`
  (matches `pad_publish_at`). Edit title: write the edited text to `suggested_title` **and** set
  `hook` to it (so `templater.build_title` yields it), then rename slug.

### WS4 — Hermes director consume side (ADR-0008)
- `scripts.status` gains the value `directed` (TEXT column; update the inline status comment in
  `schema.sql`). A **Directed script** row: `title` + `shots_json` (tagged hybrid schema) +
  `style_suffix` + `ollama_model` marked as the Hermes director model + `narration=''` +
  `status='directed'`.
- Repository: `scripts_awaiting_narration() -> list[Row]` selecting `status='directed'`; a helper
  to set narration + flip to `pending`.
- Scripter Stage B (`run_stage_b`): before/alongside generating fresh scripts, pick up
  `status='directed'` rows and run the qwen narration generator in **narration-only** mode
  (prompted from the directed title + shots + topic summary), persist narration, set
  `status='pending'`. Topics with no **Directed script** keep the existing full-generation path.
  No change needed in `gen_run` beyond Stage B feeding `pending` scripts as today.
- Add `docs/hermes-director-contract.md` (or a section in `agents.md`): the exact write contract
  for the Hermes operator — tagged shot schema, `status='directed'`, claim the topic
  (`topics.status='scripted'`), model marker, and the downstream gates that still apply.
- The **Hermes director** does not acquire `data/.weekly_run.lock`; race-avoidance is by running
  it before the Sunday `gen_run`.

## Testing Decisions

Good tests here assert **external behavior** — the DB row written, the file moved/renamed, the
refusal returned, the summary shape — never private helpers or call order. The project's existing
`tests/test_dashboard_*.py` (31 tests over view-model, scanner, run_reader, alerts_parser,
review_action, and FastAPI endpoints via `TestClient`) and the retention/scripter test suites are
the prior art to mirror. The operator chose **full coverage including endpoints**.

- **WS1:** unit-test `build_daily_run_summary` over the outcome permutations (uploaded N,
  no-candidates, orphan-abort, quota-break, exception). Integration-test `run_today` writes a
  `runs` row with the right `kind`/`success`/`summary_json` on each exit path, and writes **none**
  under `--dry-run`. Assert the dashboard `run_reader`/`view_model` render the daily tile from a
  written row (uploaded / no_candidates / Failed / In progress).
- **WS2:** unit-test the broadened retention candidate-finder returns duplicate copies across
  subdirs and respects the TTL; test `_safe_unlink` still refuses out-of-root paths. Test
  `scanner.by_basename` indexing and `_resolve_location` basename-first precedence + subdir-from-disk.
- **WS3:** unit-test `next_run` next-fire computation across day/week boundaries from fixed `now`s.
  Unit-test `clip_mutation` plans + refusals (published clip, past datetime, collision warning,
  rename targets). Endpoint-test `reschedule`/`edit-title`: `409` when the lock is held, DB-first
  ordering visible after success, `403` when `human_review` off, refusal codes, and that a published
  clip is refused.
- **WS4:** unit-test `scripts_awaiting_narration` selection and the narration-fill → `pending`
  transition. Test the scripter Stage B branch: a `directed` row gets narration and flips to
  `pending`; a fresh topic still goes full-qwen; a directed row's shots are unchanged and still hit
  the licensed/cost/policy path. Use a stubbed narration generator (no live Ollama), consistent with
  the existing scripter tests' `generator_fn` injection.

## Out of Scope

- **Dashboard v3.2:** triggering `gen_run` from the UI, editing arbitrary fields, LAN exposure +
  token auth, and any next-run **trigger** (countdown is display-only).
- **The Hermes-side setup** itself — installing/configuring the Hermes Agent, its `SOUL.md`
  director persona, model selection, and the script that writes **Directed scripts**. This PRD
  covers only the repo's *consume* side + the contract doc. (Operator + assistant task, not Composer.)
- **Original ideation beyond RSS** — the **Hermes director** directs queued **Topics**; inventing
  net-new topics outside the feed is not in scope.
- **A clip-review (vision) loop** — using a multimodal model to watch rendered **Clips** and
  critique them is a future idea (would favour `stepfun/step-3.7-flash`); not this slice.
- **Flipping `human_review` to false** — unchanged; governed by the Issue 42 hands-off trigger.
- **DB audit trail for Operator overrides** — single operator, localhost; no who/when log (same
  stance as ADR-0006).

## Further Notes

- WS1–WS4 are independent and can ship in any order; WS1 and WS2 are the smallest and unblock
  trustworthy health + a clean tree, so they're the natural first slices.
- WS3 is the first time the dashboard writes the DB (ADR-0007 extends ADR-0006); keep the
  non-published + run-lock + DB-first guardrails intact or the safety story breaks.
- WS4's repo change is small (a status + a scripter branch + a contract doc); the leverage is on
  the Hermes side, which the operator configures separately.
- Glossary terms to use throughout: **Run**, **Pipeline health**, **Review stage**, **Operator
  override**, **Hermes director**, **Directed script**, **Clip**, **Shot**, **Topic**.
