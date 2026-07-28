# Agents / Modules

Each module is a single-purpose Python package under `src/`. They communicate through the SQLite state store, not direct calls — so any stage can be re-run independently.

> **Pivot.6 status legend:**
> - ✅ Keep (unchanged or minor config-only update)
> - 🔧 Keep with changes (input contract / schema / templating update required)
> - 🆕 New module (Pivot.6)
> - ❌ Retired (Pivot.6 — code + tests deleted)

---

## ❌ `discovery/` — Discovery Agent (RETIRED Pivot.6)
Was: find candidate long-form YouTube videos by keyword, virality-score them, persist to `videos` table.
Retired because: no source-video ingestion in Pivot.6. Code + ~31 tests deleted.

## ❌ `downloader/` — Downloader (RETIRED Pivot.6)
Was: pull mp4 + caption sidecars via yt-dlp.
Retired because: no source-video ingestion in Pivot.6. Code + ~9 tests deleted.

## ❌ `lang_detect/` — Language Filter (RETIRED Pivot.6)
Was: reject non-English videos via Whisper on the first 60 s.
Retired because: no source video to classify. Code + ~14 tests deleted.

## ❌ `selector/` — Clip Selector (RETIRED Pivot.6)
Was: pick 1–3 viral 30–60 s windows per downloaded video (Whisper + heatmap + Ollama ranker).
Retired because: no source video to slice. Code + ~55 tests deleted.

---

## 🆕 `topic_ingest/` — RSS Topic Ingest (NEW Pivot.6)
**Job:** Fetch fresh tech/AI news topics from configured RSS feeds, dedup against previously-scripted stories, populate `topics` table.
**Inputs:** `config.topic_ingest.feeds` (list of RSS URLs), `config.topic_ingest.recency_hours` (48 h default), `config.topic_ingest.title_similarity_threshold`.
**Outputs:** `topics` table rows (`id`, `url`, `title`, `summary`, `source_feed`, `fetched_at`, `status='unscripted'`); `seen_topics` ledger rows for dedup (`url_hash`, `title_normalized`, `first_seen_at`).
**Dedup logic:** SHA-256 of `<link>` (exact) + normalized-title similarity (Levenshtein or word-set overlap; configurable threshold). Catches reposts across Verge / TechCrunch / Ars where the same story has different URLs.
**Library:** `feedparser` for RSS/Atom parsing.
**Failure modes:** unreachable feed → log + skip + continue with remaining feeds (not fatal). Empty result set → alert in `logs/alerts.md` (kind=`rss_empty`).
**Public interface (deep module seam):** `fetch_unscripted_topics(cfg, repo) -> list[Topic]`.

## 🆕 `scripter/` — Script Generator (NEW Pivot.6)
**Job:** Produce a complete `{title, narration, shots[], style_notes}` JSON script from one queued topic.
**Inputs:** unscripted topic row from `topics` table (title + summary), Ollama `qwen2.5:3b-instruct` JSON-mode.
**Outputs:** `scripts` table row (`script_id`, `topic_id` FK, `title`, `narration`, `shots_json`, `style_suffix`, `status='scripted'`); stub `clips` row (`content_kind='ai_generated'`, `script_id`, `video_id=NULL`).
**Rubric (locked, Tech/AI niche):** hook in first 5 words, ~40 words narration, 4 shots × ~4 s each, 1–2 punchy stats, ends on a teaser. Schema validated with pydantic; single retry on validation fail.
**Failure:** `scripts.status='rejected_policy'` if policy_gate rejects; retry up to `scripter.retry_on_policy_reject`.

## 🆕 `image_fetch/` — Real-image sourcing (Pivot.7)
**Job:** Resolve **Real-image shot** stills from **Licensed sources** only on the autonomous path (ADR-0003).
**Sources (production):** `logo` → `wikimedia` → `openverse`. Open web search (`web`) is disabled when `web_fallback_enabled: false`.
**Outputs:** cached still under `data/images/` + provenance sidecar (source/license/url).
**Probe:** `probe_licensed_image()` checks cache + licensed sources without consulting web — used by the shot-plan resolver before any billable video call.

## 🆕 `scripter/shot_plan.py` — Licensed shot-plan resolver (Pivot.7, ADR-0003)
**Job:** Given normalized shots + a licensed probe, return `(final_shots, billable_ai_video_count)`.
**Behavior:** licensed hit → **Real-image shot** unchanged. Under ADR-0009 a licensed **miss** no longer degrades straight to text-to-video — it falls to a **Generated still** which is then animated image-to-video. Wired in `gen_run._generate_clip` ahead of `generate_shots`.

## 🆕 `scripter/shot_router.py` — Image-first routing ladder (ADR-0009)
**Job:** Decide, per **Shot**, how it gets made, and refuse to bill past a ceiling.
**Ladder:** names a real entity → **Licensed source** lookup → on miss (or when no real entity is named) → **Generated still** → animate via `first_frame_path` → fallbacks `text_to_video`, then `ken_burns`.
**INV-7 (the point of the module):** a **Generated still** may never pre-empt a **Licensed source** that would have resolved. The licensed resolver runs unconditionally first, making the still call structurally unreachable on a hit; asserted by call-**order** tests, not just outcome.
**Spend:** `check_combined_clip_ceiling` reads `quota_script_total` — which spans both the video and `openrouter_still` buckets — before **every** billable still and video call, so INV-2's 150¢ per-Clip cap covers the combined total.
**Wiring status:** live for `real_image` shots via `gen_run._render_real_image_shot`. **`ai_video` shots do not yet traverse this ladder** — `route_shot` handles that case and is tested in isolation, but `_generate_clip` still batches them straight to text-to-video. Follow-up work.

## 🆕 `ai_gen/` — AI Video Generator Client (NEW Pivot.6)
**Job:** Submit shot prompts to an AI video generator, poll for completion, download mp4s.
**Design:** `base.Provider` ABC (`submit(..., first_frame_path=None)`, `poll`, `download`, `last_cost_cents`), plus `UnsupportedFirstFrameError` for providers that cannot do image-to-video — they must raise, never silently bill for an unconditioned text-to-video render. **Production impl: `openrouter_seedance.OpenRouterSeedanceClient`** (`bytedance/seedance-2.0-fast`, $0.0538/s, first-frame conditioning). **`openrouter_kling.OpenRouterKlingClient` is retained and selectable by config alone** (INV-10). The concrete class is chosen by `ai_gen/factory.build_video_provider(ai_cfg, api_key)` — `gen_run` never names a provider class directly. `factory.estimate_shot_cost_cents` derives the pre-billing projection from the **configured** per-second rate, so switching providers cannot leave the weekly cap projecting at the old model's price.
**Auth:** `OpenRouterAuthError` on 401/403 — one attempt, no retry, aborts the run with an `auth_failed` alert, and never carries key material. 5xx/timeout retry ×3.
**Inputs:** `scripts` row + `generation_jobs` table (persisted per shot for idempotency).
**Outputs:** `data/ai_gen/{script_id}/shot_{i}.mp4`; `generation_jobs.status='succeeded'`; cost recorded in `quota_usage(provider='openrouter')`.
**Concurrency:** `threading.Semaphore` with `max_concurrent_jobs=2` (config-driven).
**Cost guard:** `per_clip_cost_cents_max` enforces per-clip abort; `daily_spend_cents_ceiling` in quota_ledger enforces daily hard stop.
**Style suffix (locked, Tech/AI niche):** appended to every shot prompt — `"clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"`.

## 🆕 `narration/` — TTS Narration (NEW Pivot.6)
**Job:** Convert `script.narration` text → mp3 + per-word timings.
**Engine:** `edge-tts` (free, Microsoft neural voices). Voice: `en-US-GuyNeural`, rate `+10%`, pitch `0Hz` — natural conversational pacing (engaged-friend cadence; not calm/slow, not crammed).
**Word timings:** Whisper `large-v3` int8_float16 on CUDA run on the TTS mp3 → forced-align word timestamps. TTS audio is always clean → very fast/accurate transcription.
**Outputs:** `data/narration/{script_id}.mp3` + word-timings dict (used by subtitle writer).
**Degraded mode:** `pyttsx3` offline fallback if Edge TTS is throttled.

---

## 🔧 `assembler/` — Clip Assembler (replaces `editor/`, Pivot.6)
**Job:** Render the final 1080×1920 Short from generated shots + narration.
**Inputs:** list of shot mp4s (heterogeneous resolution/fps in Pivot.7 hybrid) + narration mp3 + subtitle ASS file + optional music track.
**Outputs:** `output/pending/__unscheduled__{clip_id}__{title_slug}.mp4`; `clips.status='rendered'`.
**Pipeline (single ffmpeg invocation):**
1. **Shot normalization** (ADR-0002, `src/assembler/normalize.py`) — each input is scaled/padded to `cfg.output_resolution`, conformed to `cfg.output_fps`, yuv420p, SAR 1:1. Required because the configured video Provider's output (resolution and fps are provider-specific and not assumed) must combine with Ken Burns fallback **Real-image shots** at 1080×1920@30.
2. **Stitch** 4–6 shots — `xfade` when `assembler.crossfade_enabled`, else concat filter on normalized inputs (not the concat demuxer).
3. Mux narration mp3 as sole audio track (replace source audio).
4. Mix music bed at −22 dB with auto-duck under narration (reuses `editor/music.py` helpers).
5. Burn ASS subtitle file (line-at-a-time, from `subtitles/`).
6. NVENC encode (`h264_nvenc`, libx264 CPU fallback on encoder failure): `h264_nvenc -preset p5 -cq 23 -movflags +faststart`, 2-pass loudness to −14 LUFS.
**Reused from `editor/`:** `music.py` (track picker + mix), `ffmpeg_runner.py` (NVENC helpers), `slug.py` (filename slug).
**Dropped from `editor/`:** blurred-bg split/gblur/overlay filtergraph. Karaoke subtitle path (replaced by line-at-a-time in `subtitles/`).

## 🔧 `subtitles/` — Subtitle Generator (Pivot.6: line-at-a-time)
**Job:** Convert per-word timings (from `narration/`) into a line-at-a-time centered `.ass` file.
**Style:** Anton font, 64pt, white fill, 8px black border. Position: `\pos(540, 1500)` (~78% down). Lines broken at ≤28 chars on natural word boundaries, 100 ms fade-in.
**Breaking change from Pivot.5:** karaoke word-by-word highlighting replaced by centered line-at-a-time. Old karaoke writer archived to `src/subtitles/_karaoke_legacy.py` for one pivot.

---

## 🔧 `policy_gate/` — Policy & Safety Gate (input contract updated Pivot.6)
**Job:** Block scripts/clips that would risk ToS violations or misleading metadata. Runs **twice**: post-script (before generation) and pre-upload (in `daily_upload.py`).
**Input change (Pivot.6):** `clip_text` = `script.narration` (not a Whisper transcript of source video). `recheck_title` = `script.title`.
**Checks (unchanged):** banlist substring match · profanity scoring (`better-profanity`) · NSFW zero-shot via Ollama · hook-vs-content sanity (Ollama: does title summarize narration?) · topic_filter (re-tuned for new topic pool).
**Failure:** `scripts.status='rejected_policy'` (pre-gen) or `clips.status='rejected_policy'` (pre-upload). `rejection_reason` populated.

## 🔧 `quality_screen/` — Content Quality Screen (gates updated Pivot.6)
**Job:** Block low-quality or duplicate output before it enters the upload queue.
**Checks active for `content_kind='ai_generated'`:**
- `duration.py` — final clip ∈ [25, 65] s.
- `loudness.py` — integrated loudness within ±1.5 LUFS of −14.
- `dedup.py` — pHash on 5 frames + (optionally) script-text hash to prevent narrative repetition. Stored in `dup_hashes`, matched over last 90 days.
**Checks SKIPPED for `content_kind='ai_generated'`:** `density.py` (speech density) and `confidence.py` (word confidence) — TTS output is always clean; these gates add no value and would false-positive on silence in generated video.

## 🔧 `uploader/` — YouTube Uploader (templating updated Pivot.6)
**Job:** Publish a `quality_pass` (or `approved`) clip to YouTube as a Short with a future `publishAt`.
**Unchanged:** orphan-marker fence, pre-upload re-check, quota guard, dry-run mode, `publish_at_utc` padding (20 min lead), resumable upload with tenacity.
**Changed for Pivot.6 (`content_kind='ai_generated'`):**
- `templater.py` — description drops `Source: url` + `Original channel: name`; replaces with `compliance.description_footer` ("Made with AI. For entertainment / educational use.") + topic hashtag. Tags from `upload_extra_tags` config key.
- `insert_body.py` — `status.containsSyntheticMedia=true` set when `content_kind='ai_generated'` and `compliance.ai_disclosure=true`. Field confirmed live in YouTube Data API v3 since 2024-10-30.
- `runner.py` — `get_clip_with_video` join becomes LEFT JOIN; templater receives `content_kind` for routing.

## 🔧 `quota_ledger/` — Per-Endpoint Quota Tracker (provider dimension added Pivot.6)
**Job:** Prevent silent quota overruns across all billed APIs.
**Schema update:** `quota_usage` gains `provider TEXT NOT NULL DEFAULT 'youtube'`. Existing rows backfill to `'youtube'`.
**New provider:** `provider='openrouter'`, `units=cost_cents`. Daily ceiling enforced separately from YouTube units.
**API unchanged:** `record(endpoint, units, provider)`, `today_total(provider)`, `would_exceed(units, ceiling, provider)`.

## 🔧 `state/` — State Store (schema bridge Pivot.6)
**Schema additions:**
- `clips.content_kind TEXT NOT NULL DEFAULT 'sourced'` — `'sourced'` (legacy) | `'ai_generated'` (Pivot.6+).
- `clips.script_id TEXT` — FK → `scripts(script_id)`, nullable.
- `clips.video_id` — relaxed to nullable for `ai_generated` rows (was NOT NULL).
- `topics` table (new) — `id PK, url, title, summary, source_feed, fetched_at, status`. Status: `'unscripted' | 'scripted' | 'expired'`.
- `seen_topics` table (new) — `url_hash PK, title_normalized, first_seen_at`. Dedup ledger.
- `scripts` table (new) — `script_id PK, topic_id FK, title, narration, shots_json, style_suffix, ollama_model, created_at, status`.
- `generation_jobs` table (new) — `job_id PK, script_id, shot_index, provider, prompt, duration_s, status, external_id, output_path, cost_cents, submitted_at, completed_at, error`.
- `quota_usage.provider` column (new).
**Tables NOT dropped (Pivot.6):** `videos`, `dup_hashes`, `niche_baselines`, `discovery_attempts` — inert for new content but referenced by historic rows. Drop in a future cleanup pivot.
**New repository helpers:** `insert_topic`, `seen_topics_in_window`, `mark_topic_scripted`, `insert_script`, `insert_generation_job`, `update_job_status`, `clips_for_generation_run`, `get_clip_with_script`.

## ✅ `slot_planner/` — Slot Planner (unchanged)
**Job:** Assign `publish_at_utc` timestamps to rendered clips, spaced evenly across the next `days_per_run` days at configured slots. Rename files in place. Missed-slot recovery batches stale → next future slot. Future-too-near pad of 20 min.

## 🔧 `retention/` — Cleanup (TTLs updated Pivot.6)
**New TTLs:** `data/ai_gen/{script_id}/` — 7 d post-render. `data/narration/` — 14 d. `scripts` rows — 90 d. `topics` rows — 30 d post-`fetched_at`.
**Dropped TTLs:** `data/raw/*.mp4` (14 d) and `data/transcripts/*.json` (90 d) — no longer produced.
**Unchanged:** `output/pending|approved` 7 d post-upload, `dup_hashes` 90 d, `quota_usage` 90 d, monthly VACUUM.

## ✅ `observability/` — Logging & Alerts (unchanged)
**Stack:** `loguru` → `logs/agent.log` (daily rotation, 30-day retention). `logs/alerts.md` — one row appended on: weekly run finished, run failure, quota > 80% used (per provider), upload rejected, missed-slot recovery, OpenRouter spend near cap, `rss_empty`. `logs/runs.md` — per-run summary (kind, started_at, finished_at, success, summary).

## ✅ `config_loader/` — Config Loader (new keys added, otherwise unchanged)
New config sections: `topic_ingest.*`, `ai_gen.*`, `scripter.*`, `narration.*`, `subtitles.*`, `compliance.*`. Old discovery/lang_detect/selector/blurred_bg keys moved to `config.archive.yaml`.

## 🔧 `bootstrap.py` — Environment Health Check (updated Pivot.6)
**New checks:** `OPENROUTER_API_KEY` env var set, `edge-tts` importable, `feedparser` importable, ffmpeg concat smoke, Whisper load. **Dropped check:** `yt-dlp` availability, direct `KLING_API_KEY`.

## ✅ `daily_upload.py` — Daily Upload Entrypoint (unchanged)
Reads `clips_for_upload_due()`, runs policy re-check, calls uploader. Run lock + `runs.md` writer. `--dry-run` aware. Content-agnostic — templating branch is inside `uploader/`.

## 🆕 `gen_run.py` — Weekly Generation Entrypoint (NEW Pivot.6, replaces `weekly_run.py`)
**Job:** Full weekly orchestration: `topic_ingest → scripter → policy_gate → ai_gen → narration → assembler → quality_screen → slot_planner → retention`. Run lock (`data/.weekly_run.lock`) + `runs.md` writer. `--dry-run` and `--clips N` flags.

---

## Data Flow (Pivot.6)
```
RSS feeds → [topic_ingest] (feedparser; 48h window; URL + title-similarity dedup → topics + seen_topics tables)
                        ↓
                  [scripter] (Ollama qwen2.5:3b on topic.title+summary → scripts table + clips stub, content_kind='ai_generated')
                        ↓
               [policy_gate] (banlist/profanity/NSFW/hook_sanity on narration+title)
                        ↓
                  [ai_gen] (config-selected Provider — Seedance 2.0 Fast — × 4 shots × ~4s, threading.Semaphore, generation_jobs table) → data/ai_gen/{script_id}/shot_{i}.mp4
                           real_image: licensed still → (miss) Generated still → first_frame → i2v | ken_burns fallback
                           ai_video:   text-to-video (ladder not yet wired for this path)
                        ↓
                [narration] (Edge TTS +10%/0Hz → mp3; Whisper forced-align → word timings) → data/narration/{script_id}.mp3
                        ↓
               [assembler] (Shot normalize → Stitch shots [xfade or concat filter] → mux narration → music-bed duck → ASS line-burn → NVENC/libx264 1080×1920 → −14 LUFS)
                        ↓ output/pending/__unscheduled__{clip_id}__{slug}.mp4
          [quality_screen] (duration, loudness, pHash dedup)
                        ↓
             [slot_planner] → clips.publish_at_utc + filename rename
                        ↓
               [retention] (cleanup + VACUUM)
                        ↓
(Windows Task Scheduler — daily) → [daily_upload] →
                  [policy_gate] (re-check) → [uploader] (quota_ledger metered, orphan-marker fence, --dry-run aware) → YouTube (scheduled)
                        ↑
         [observability] (loguru → logs/agent.log + logs/alerts.md) ← every stage
```
