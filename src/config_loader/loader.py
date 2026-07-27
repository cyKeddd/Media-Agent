from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from src.config_loader.weekdays import parse_upload_weekdays


# ---------------------------------------------------------------------------
# Pivot.6 sub-models
# ---------------------------------------------------------------------------


class NicheGateConfig(BaseModel):
    enabled: bool = True
    low_yield_threshold: int = 1
    recency_hours_extended: int = 96


class HnConfig(BaseModel):
    enabled: bool = True
    top_stories_url: str = "https://hacker-news.firebaseio.com/v0/topstories.json"
    item_url_template: str = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
    max_stories: int = 30
    corroboration_weight: float = 2.0
    # Issue 69 — promote HN front-page to a Topic source (in addition to its
    # existing Trending-corroboration ranking role, which is unaffected).
    topic_source_enabled: bool = True


class TopicIngestConfig(BaseModel):
    feeds: list[str] = Field(default_factory=list)
    recency_hours: int = 48
    seen_topics_window_days: int = 30
    jaccard_threshold: float = 0.6
    stopwords: list[str] = Field(default_factory=lambda: [
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "at", "by", "for", "from", "in",
        "of", "on", "to", "up", "with", "about", "after", "and", "as", "but",
        "if", "into", "or", "so", "than", "that", "this", "too", "when",
        "where", "while", "just", "it", "its", "says", "said", "new", "over",
    ])
    niche_gate: NicheGateConfig = Field(default_factory=NicheGateConfig)
    hn: HnConfig = Field(default_factory=HnConfig)


class AiGenConfig(BaseModel):
    model: str = "kwaivgi/kling-v3.0-std"
    per_clip_cost_cents_max: int
    daily_spend_cents_ceiling: int
    # Issue 62 — rolling 7x24h OpenRouter spend ceiling (INV-1). Default 800c
    # matches the $8/week budget; gen_run refuses billable calls that would
    # cross it rather than issuing them and finding out after the fact.
    weekly_spend_cents_ceiling: int = 800
    # Issue 62 — INV-3 config keys for the still provider landing in Issue 64.
    # Enforcement is not wired up here; these just stop the ceiling from
    # drifting once the still provider exists.
    still_cost_cents_max: int = 5
    still_clip_cost_cents_max: int = 20
    # Issue 64 — Nano Banana 2 (google/gemini-3.1-flash-image) still model id,
    # read from config so NanoBananaProvider never hardcodes it (INV-10).
    still_model: str = "google/gemini-3.1-flash-image"
    max_concurrent: int = 2
    shots_per_clip_min: int = 1
    shots_per_clip_max: int = 3
    shot_duration_s: int = 5
    style_suffix: str = (
        "3D animated, Pixar-shaded surface, surreal cinematic lighting, "
        "vertical 9:16, photoreal textures with stylized characters, dark moody atmosphere"
    )
    # Seedance 2.0 Fast image-to-video (ADR-0009, Issue 65). Model id and
    # per-second rate live here — never hardcoded in openrouter_seedance.py —
    # so the cost projection INV-1/INV-2 depend on is config-driven.
    seedance_model: str = "bytedance/seedance-2.0-fast"
    seedance_rate_cents_per_second: float = 5.38


class TopicScoreWeights(BaseModel):
    novelty: float = 0.4
    specificity: float = 0.3
    tension: float = 0.3


class ScriptScoreWeights(BaseModel):
    hook_execution: float = 0.4
    pacing: float = 0.3
    payoff: float = 0.3


class ScripterConfig(BaseModel):
    categories: list[str] = Field(default_factory=lambda: [
        "ai_models", "ai_features", "hardware", "software",
        "policy", "business", "science_research", "startup_funding",
    ])
    candidate_pool_size: int = 4
    topic_score_weights: TopicScoreWeights = Field(default_factory=TopicScoreWeights)
    script_score_weights: ScriptScoreWeights = Field(default_factory=ScriptScoreWeights)
    quality_floor: float = 6.0
    weekly_clip_target: int = 2
    style_suffix: str = (
        "clean editorial product photography, soft studio lighting, "
        "neutral backgrounds, minimalist composition, sharp focus, "
        "vertical 9:16, premium tech magazine look"
    )
    narration_word_count_min: int = 30
    narration_word_count_max: int = 50
    hook_word_count: int = 5
    banned_tokens: list[str] = Field(default_factory=lambda: [
        "<<placeholder>>", "I think", "as an AI",
    ])
    retry_on_failure: int = 3
    source_authority: dict[str, float] = Field(default_factory=dict)


class NarrationConfig(BaseModel):
    engine: Literal["kokoro", "edge"] = "kokoro"
    kokoro_voice: str = "am_michael"
    voice: str = "en-US-GuyNeural"
    rate: str = "+10%"
    pitch: str = "0Hz"

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        if value not in ("kokoro", "edge"):
            raise ValueError(f"narration.engine must be 'kokoro' or 'edge', got {value!r}")
        return value


class AssemblerConfig(BaseModel):
    crossfade_enabled: bool = True
    crossfade_duration_s: float = 0.25


class ImageFetchConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: [
        "logo", "wikimedia", "openverse", "web",
    ])
    min_resolution: int = 512
    max_candidates_per_source: int = 5
    web_fallback_enabled: bool = True
    living_person_patterns: list[str] = Field(default_factory=lambda: [
        "portrait of", "photo of", "headshot", "selfie",
    ])


class SubtitlesConfig(BaseModel):
    position_x: int = 540
    position_y: int = 1500
    font_size: int = 52
    font_name: str = "Arial"


class ComplianceConfig(BaseModel):
    ai_disclosure: bool = True


# ---------------------------------------------------------------------------
# Core sub-models (retained from previous phases)
# ---------------------------------------------------------------------------


class Retention(BaseModel):
    # Pivot.6 TTLs
    ai_gen_shots: int = 7
    narration: int = 14
    scripts: int = 90
    images: int = 30
    # Retained
    output_post_upload: int
    rejected_clips: int
    dup_hashes: int
    quota_usage: int
    vacuum_every_days: int


class Paths(BaseModel):
    state_db: str
    pending_dir: str
    approved_dir: str
    rejected_dir: str
    dry_run_dir: str
    orphans_dir: str = "output/orphans"
    logs_dir: str
    oauth_token: str
    client_secrets: str
    # Retained with defaults so older config.yaml files keep working
    raw_dir: str = "data/raw"
    transcripts_dir: str = "data/transcripts"
    music_dir: str = "data/music"
    # Pivot.6 dirs
    ai_gen_shots_dir: str = "data/ai_gen_shots"
    narration_dir: str = "data/narration"
    scripts_dir: str = "data/scripts"
    images_dir: str = "data/images"


# ---------------------------------------------------------------------------
# Top-level Config (Pivot.6)
# ---------------------------------------------------------------------------


class Config(BaseModel):
    # Cadence
    clips_per_day: int
    days_per_run: int
    upload_slots: list[str]
    timezone: str
    upload_weekdays: frozenset[int] = Field(default_factory=lambda: frozenset(range(7)))

    @field_validator("upload_weekdays", mode="before")
    @classmethod
    def _coerce_upload_weekdays(cls, value: object) -> frozenset[int]:
        if isinstance(value, frozenset):
            return value
        if value is None:
            return parse_upload_weekdays(None)
        if isinstance(value, (list, tuple)):
            return parse_upload_weekdays(list(value))
        raise ValueError(f"upload_weekdays must be a list of weekday tokens, got {type(value)!r}")

    # Models
    whisper_model: str
    whisper_compute_type: str
    whisper_device: str
    ollama_model: str

    # Policy gate
    human_review: bool
    banlist: list[str]
    hook_sanity_min_score: int
    profanity_max_score: int

    # Quality screen
    min_speech_density: float = 1.5
    min_word_confidence: float = 0.6
    dedup_lookback_days: int
    phash_min_hamming: int

    # Assembler / render
    output_resolution: list[int]
    output_fps: int = 30
    nvenc_preset: str
    nvenc_cq: int
    loudness_target_lufs: float
    music_enabled: bool = True
    music_volume_db: float = -15.0
    blurred_bg_sigma: int = 20
    ken_burns_zoom_rate: float = 0.0015
    ken_burns_gradient_luma_max: int = 45
    ken_burns_gradient_saturation_max: float = 0.35
    copyright_acknowledgement: str | None = None

    # Pivot.7 sub-models
    image_fetch: ImageFetchConfig = Field(default_factory=ImageFetchConfig)
    assembler: AssemblerConfig = Field(default_factory=AssemblerConfig)

    # Quota
    youtube_quota_daily_units: int
    youtube_quota_ceiling_units: int
    videos_insert_unit_cost: int

    # Run hang detection (Issue 60) — a runs row with finished_at IS NULL
    # older than this many minutes is swept to success=0 at the next
    # entry-point start. Matches INV-11's gen_run wall-clock budget.
    run_hang_minutes: int = 90

    # Liveness detection (Issue 61 / INV-5) — if no Clip has been rendered
    # within this many days, a `liveness_stalled` alert is appended on the
    # next run of either entry point (at most once per calendar day).
    liveness_stale_days: int = 7

    # Pivot.6 sub-models
    topic_ingest: TopicIngestConfig = Field(default_factory=TopicIngestConfig)
    ai_gen: AiGenConfig
    scripter: ScripterConfig = Field(default_factory=ScripterConfig)
    narration: NarrationConfig = Field(default_factory=NarrationConfig)
    subtitles: SubtitlesConfig = Field(default_factory=SubtitlesConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)

    # Nested
    retention: Retention
    paths: Paths

    project_root: Path = Field(default_factory=Path.cwd, exclude=True)

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def load_config(path: str | Path = "config.yaml") -> Config:
    cfg_path = Path(path).resolve()
    with cfg_path.open("r") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    cfg = Config(**raw)
    cfg.project_root = cfg_path.parent
    return cfg
