# Tools, Libraries & APIs

> **Pivot.6 (current — Tech/AI news):** yt-dlp and mostReplayed are no longer used. Ollama's role has shifted from clip-ranker to script-writer. New additions: edge-tts (TTS narration), `feedparser` (RSS topic ingest), Whisper now used for forced-alignment of TTS output rather than source-video transcription.
>
> **ADR-0009 (2026-07-27) — image-first generation:** the video generator is now **OpenRouter Seedance 2.0 Fast** image-to-video, selected from config via `src/ai_gen/factory`, with **Nano Banana 2** producing **Generated stills**. Kling 3.0 std is retained and revertible by config alone (INV-10), but is no longer the production path.

## Language & Runtime
- **Python 3.11+** — best ecosystem fit for all project dependencies. Single-language project.
- **ffmpeg** (system binary, Gyan 8.1-full_build) — concat, mux, loudnorm, ASS burn, NVENC encode. Must be on PATH.

## AI Video Generation (NEW — Pivot.6)
- **OpenRouter Seedance 2.0 Fast** (`bytedance/seedance-2.0-fast`, via OpenRouter REST API, `OPENROUTER_API_KEY`) — **image-to-video** generator, the production path since ADR-0009. **$0.0538/s → 22¢ per 4 s shot** (rounded up, so the ledger never under-reports). Supports first-frame conditioning, which is the whole reason for the switch: text-to-video re-rolls composition on every retry and drifts in style across the four **Shots** of a **Clip**, whereas conditioning on a still fixes the subject and lets a **Licensed source** image be the literal first frame. Implementation: `src/ai_gen/openrouter_seedance.py`.
- **OpenRouter Nano Banana 2** (`google/gemini-3.1-flash-image`, ~$0.004/still) — the **Still provider** that produces a **Generated still** when a **Licensed source** misses or a **Shot** names no real entity. Implementation: `src/image_gen/nano_banana.py`.
- **Provider seam:** `src/ai_gen/base.Provider` ABC (now carrying `first_frame_path`) and `src/image_gen/base.StillProvider`. The concrete video class is chosen by `src/ai_gen/factory.build_video_provider` from config — `gen_run` never names one, so reverting to Kling is a one-line config edit (INV-10). **Kling is retained**, not deleted (`src/ai_gen/openrouter_kling.py`); the direct-Kling JWT adapter (`src/ai_gen/kling.py`) also remains as a legacy fallback (was blocked on error 1003 "Authorization not active").
- **Why OpenRouter:** API activation is immediate, billing aggregates across providers in one place, a single env var simplifies key rotation, and it serves both the video and still models. Switching providers requires no downstream pipeline changes.
- **Cost model:** per-second pricing; **$8/week budget → 5 clips/week at ~88¢/clip** (4 × 22¢ Seedance shots ≈ 86¢ + ~2¢ stills), ≈ $4.40/week, ~45% headroom for retries. Enforced *before* each billable call by `weekly_spend_cents_ceiling` (800¢ rolling 7×24 h), `per_clip_cost_cents_max` (150¢, combined video + stills), `daily_spend_cents_ceiling` (300¢ burst guard) and the INV-3 still ceilings (5¢/still, 20¢/Clip). The projection itself comes from `factory.estimate_shot_cost_cents`, derived from the configured rate rather than a constant — a hardcoded 67¢ (Kling's price) would have made the 800¢ ceiling behave like ~260¢ after the switch and quietly strangled output.

## TTS Narration (NEW — Pivot.6)
- **`edge-tts`** (PyPI, free) — Microsoft Azure neural TTS via the unofficial public endpoint. No API key required. Voice `en-US-GuyNeural`. Rate `+10%`, pitch `0Hz` — natural conversational pacing (not slow/calm, not crammed; engaged-friend cadence).
- Why free over ElevenLabs: user requirement is zero additional paid services. Edge TTS quality is acceptable for this format.
- **Degraded-mode fallback:** `pyttsx3` (offline, SAPI5 voices) if Edge TTS throttles. Quality is lower but non-blocking.

## RSS Topic Ingest (NEW — Pivot.6)
- **`feedparser`** (PyPI) — RSS/Atom feed parsing. Pulls last-48h items from mixed consumer + research tech/AI feeds. Source-of-truth for topic selection; replaces the static `topic_pool` config.
- **Dedup:** URL hash (SHA-256 of `<link>`) + normalized-title similarity (Levenshtein or word-set overlap, configurable threshold). Catches reposts where the same story has different URLs across Verge / TechCrunch / etc.
- **Feed list:** user-curated, configured at Slice 7. Documented in `docs/rss_feeds.md`.

## Hybrid real-image shots (Pivot.7)
- **`image_fetch`** — resolves **Real-image shot** stills from **Licensed sources** (logo APIs, Wikimedia, Openverse). Production config: `web_fallback_enabled: false` (ADR-0003). Open web search remains available for manual spike/dev configs only.
- **`scripter/shot_plan.resolve_shot_plan`** — resolves licensed stills up front so the billable count is known before any spend.
- **`scripter/shot_router.route_shot`** (ADR-0009) — the image-first ladder: licensed still → **Generated still** on a miss → animate as first frame → `text_to_video` → `ken_burns`. **INV-7** is enforced structurally (licensed lookup runs first, making the still call unreachable on a hit) and proven by call-**order** assertions. Live for `real_image` shots; `ai_video` shots still go straight to text-to-video pending follow-up wiring.
- **Ken Burns** (`src/assembler/ken_burns.py`) — motion over sourced still → 1080×1920@30 mp4.
- **Shot normalization** (ADR-0002) + **Stitch** (ADR-0002 assembler) — heterogeneous provider-generated + Ken Burns shots combined at 1080×1920. Whatever resolution/fps the configured video Provider returns is conformed here; nothing downstream assumes Kling's 720×1280 @ 24fps.

## Video Acquisition (LEGACY — not used in Pivot.6)
- **`yt-dlp`** (Python API) — was used for YouTube source-video downloads and caption sidecar retrieval (Phases 1–7, Pivots.0–5). Retained in `requirements.txt` but no code path calls it in Pivot.6. Will be removed when the `discovery/` and `downloader/` modules are fully deleted.

## Upload
- **YouTube Data API v3** via **`google-api-python-client`** — used for `videos.insert` (resumable upload) with `publishAt` + `status.containsSyntheticMedia` disclosure flag. `search.list` and `videos.list` no longer called (discovery retired in Pivot.6).
- **`google-auth-oauthlib`** — handles OAuth desktop flow; refresh-token cached at `data/oauth_token.json`.
- **`requests`** — HTTP client for Ollama API calls and (previously) `mostReplayed` heatmap endpoint.

## Transcription / Forced Alignment (ROLE CHANGED — Pivot.6)
- **`faster-whisper`** — now used exclusively for **forced alignment**: run on the Edge TTS mp3 output to extract per-word timings for the subtitle writer. No longer used on source video (no source video). Model: `large-v3` `int8_float16` on CUDA. Fits the RTX 3070 with headroom.
- Requires CUDA 12.x + cuDNN 9 on the PC (already installed).

## Script Writing / Policy / Hook-Sanity (LLM — ROLE CHANGED — Pivot.6)
- **Ollama** running locally on the PC, model **`qwen2.5:3b-instruct`** (q4_K_M ≈ 2 GB VRAM). Fits the RTX 3070 alongside Whisper. JSON-mode output.
- **Old role (Pivots.0–5):** clip ranking, NSFW transcript classifier, hook-vs-content sanity check.
- **New role (Pivot.6):** script writer — given a topic seed, produces `{title, narration, shots[], style_notes}` JSON. NSFW classifier and hook-sanity check still run, now on the generated narration + title.
- Quality note: 3B-class instruct models are sufficient for rubric-style script generation. Swap to `qwen2.5:7b-instruct` (≈ 5 GB VRAM) by changing one config line if quality is inadequate.

## Editing & Rendering
- **`ffmpeg-python`** (or raw subprocess) — composes the vstack + crop + subtitle-burn + loudnorm filtergraph in a single pass for speed.
- **NVENC (`h264_nvenc`)** — hardware-accelerated H.264 encoding on the RTX 3070; chosen over libx264 for ~5× faster renders, which matters when a single pipeline run produces multiple clips.
- **ASS subtitles** (libass via ffmpeg) — only practical way to get karaoke-style word highlighting burned into video.
- **`Pillow`** — generate ASS-incompatible overlays (e.g., title cards) if needed.

## Scheduling
- **Windows Task Scheduler** — host-level cron. Triggers `weekly_run` (weekly) and `daily_upload` (daily). No long-running Python daemon needed.
- **YouTube native scheduling** — `status.publishAt` on the insert call lets YouTube auto-publish at a future timestamp. We use this so the daily uploader can hand off all that day's clips at once and YouTube spaces out the actual publish times.

## State & Config
- **SQLite** via stdlib `sqlite3` — file-based, zero-ops, perfect for single-process pipeline state.
- **`pydantic`** + **`pyyaml`** — typed config loading from `config.yaml`.
- **`python-dotenv`** — load secrets from `.env`.

## Logging & Reliability
- **`loguru`** — structured logs with rotation, far less ceremony than stdlib logging.
- **`tenacity`** — retry decorators with exponential backoff for API/network calls.
- **`requests`** — used for Ollama HTTP calls and `mostReplayed` heatmap fetch.

## Human-in-the-Loop & Review
- **File-system as queue.** No Discord, no webhooks. Rendered clips drop into `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`. The user reviews in Explorer; approved clips are moved to `output/approved/`; the daily uploader reads from `output/approved/` while `human_review=true`. After 2 weeks (or when the user flips the toggle), pipeline writes directly to `output/pending/` and uploader treats `output/pending/` as the publish queue.
- **Alerts log:** failures and recoveries append a line to `logs/alerts.md` (markdown table). User glances at this file once a day. No push notification mechanism in v1.

## Content Safety (v1.1)
- **`better-profanity`** — fast lexical profanity score; baseline gate before LLM checks.
- **Ollama (re-used)** — zero-shot NSFW transcript classifier and "hook accurately summarizes content?" sanity check. Same model as the ranker, just different prompts.
- *Configurable banlist* (substring match on transcript + suggested title) lives in `config.yaml`, not in code, so it can be tuned without redeploys.

## Dedup (v1.1)
- **`imagehash`** — perceptual hash (pHash) on 5 evenly-spaced frames per rendered clip. Stored in `dup_hashes` and matched by Hamming distance across the last 90 days.
- **`chromaprint` / `acoustid-tools`** — audio fingerprint stored alongside pHash for cross-modal dedup. Catches re-uploads where visuals differ but audio is the same clip.

## Time
- **`zoneinfo`** (stdlib) — canonical timezone handling with DST correctness. `publish_at_utc` stored in DB; converted to/from canonical TZ at the boundary.

## Dev Tooling
- **`uv`** or **`pip` + `requirements.txt`** — `uv` is faster but `pip` is fine.
- **`ruff`** — lint + format in one binary.

## What we are *not* using and why
- **MoviePy** — too slow; abstracts away the ffmpeg filtergraph we need fine control over.
- **OpenCV** — not needed; ffmpeg handles all cropping/scaling.
- **APScheduler / Celery / Redis / Postgres** — overkill; Windows Task Scheduler + native YouTube `publishAt` cover the scheduling needs.
- **Learned dedup model (CLIP / video embeddings)** — `imagehash` pHash is sufficient at this scale. A learned model adds GPU dependency + training pipeline for ~zero accuracy gain at 90-day, single-channel scope.
- **Email-on-critical alerting / Discord webhooks** — `logs/alerts.md` is sufficient for v1 (single-user, on-demand reading).
- **TikTok / Instagram SDKs** — out of scope per user.
- **Cloud transcription (AssemblyAI, Deepgram)** — local Whisper is free and accurate enough for forced-alignment on clean TTS audio.
- **ElevenLabs / OpenAI TTS** — Edge TTS is free; paid TTS adds a second paid dependency. Revisit if voice quality is inadequate.
- **Runway Gen-3 / Sora** — Runway is expensive and cinematic-skewed (weak for 3D-animated); Sora is not publicly accessible via API.

## Cost Model (Pivot.6)
- Edge TTS / Whisper / Ollama / ffmpeg / YouTube API / RSS fetching: all **free**
- **OpenRouter Seedance 2.0 Fast:** ~86¢/clip at 4 shots × ~4 s ($0.0538/s → 22¢/shot). **$8/week budget → 5 clips/week** (current cadence).
- **OpenRouter Nano Banana 2 stills:** ~$0.004/still, ~2¢/clip.
- **Total: ~88¢/clip → ≈$4.40/week** at 5 clips/week, against an 800¢ weekly ceiling. Only paid dependency. (For reference, the retired Kling text-to-video path was ~$2/clip — the image-first switch cut per-clip cost by ~55% *and* raised quality.)
