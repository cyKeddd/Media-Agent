"""Pivot.6 weekly generation orchestrator.

Replaces weekly_run.py for the AI-generated pipeline:
  topic_ingest → scripter A/B/C
  → per-script: pre-billing policy + licensed resolve + ai_gen + narration + assemble
  → quality_screen → slot_planner → retention

Usage:
    python -m src.gen_run [--dry-run] [--clips N] [--config config.yaml]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

from src.config_loader import Config, load_config

# Project root — used to locate .env (Issue 59). Scheduler-driven entry points
# never inherit a shell profile, so the process env alone cannot be trusted to
# carry OPENROUTER_API_KEY etc; .env must be loaded explicitly before config
# resolution.
ROOT = Path(__file__).resolve().parent.parent


def load_env_file(root: Path = ROOT) -> None:
    """Load `.env` into os.environ, without clobbering variables the real
    environment already set. A missing .env file is not an error — the env
    may legitimately be populated by the shell/scheduler."""
    load_dotenv(root / ".env", override=False)
from src.observability import (
    RunLockHeld, acquire_run_lock, append_alert, append_run_row,
    check_liveness, setup_logging,
)
from src.state import Repository, connect

# Stage imports — imported into this namespace so tests can patch at src.gen_run.*
from src.topic_ingest.runner import fetch_unscripted_topics
from src.scripter.runner import run_stage_a, run_stage_b, run_stage_c
from src.scripter.ollama_fns import (
    make_narration_generator,
    make_script_generator,
    make_script_scorer,
    make_topic_scorer,
    make_topic_tagger,
)

from src import quality_screen, slot_planner, retention

# Per-clip stage imports at module level so tests can patch src.gen_run.*
from src.ai_gen.openrouter_kling import OpenRouterKlingClient
from src.ai_gen.openrouter_seedance import OpenRouterSeedanceClient
from src.quota_ledger.ledger import SpendCapReached
from src.ai_gen.base import GenerationStatus, OpenRouterAuthError, UnsupportedFirstFrameError
from src.ai_gen.runner import DEFAULT_SHOT_COST_ESTIMATE_CENTS, generate_shots
from src.assembler.build import build_assembler_argv, write_concat_list
from src.assembler.ken_burns import build_ken_burns_argv
from src.editor.ffmpeg_runner import run_ffmpeg
from src.editor.music import SUPPORTED_EXTENSIONS
from src.editor.slug import title_slug
from src.image_fetch.fetcher import fetch_image, resolve_licensed_image
from src.image_fetch.errors import ImageFetchError
from src.narration.aligner import align
from src.narration.synth import synthesize
from src.policy_gate.evaluator import evaluate_clip_policy
from src.scripter.shots import normalize_shots
from src.scripter.shot_plan import resolve_shot_plan
from src.scripter.shot_router import ClipCostCeilingError, check_combined_clip_ceiling
from src.subtitles.line_ass import write_line_ass_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize(results: Any) -> Any:
    if results is None:
        return None
    if isinstance(results, list):
        return {"count": len(results)}
    if hasattr(results, "__dict__"):
        return {k: v for k, v in vars(results).items() if not k.startswith("_")}
    return {"value": str(results)[:120]}


def _build_runs_md_summary(summary: dict) -> str:
    stages = summary.get("stages") or {}
    bits = []
    for name, s in stages.items():
        if isinstance(s, dict) and "count" in s:
            bits.append(f"{name}={s['count']}")
        else:
            bits.append(name)
    base = "stages={" + ", ".join(bits) + "}"
    if "error" in summary:
        base += f"; error={summary['error']}"
    return base


def sweep_abandoned_runs(repo: Repository, cfg: Config, logs_dir: Path) -> None:
    """Finalize `runs` rows abandoned by a hard process death (Issue 60).

    MUST be called only after the run lock is held — see acquire_run_lock in
    main(). A genuinely in-flight run held by another process is never swept
    because its lock prevents this process from reaching this call at all.
    """
    hang_minutes = getattr(cfg, "run_hang_minutes", 90)
    swept = repo.sweep_abandoned_runs(hang_minutes)
    for row in swept:
        append_alert(
            logs_dir, kind="run_abandoned",
            message=(
                f"run {row['run_id']} (kind={row['kind']}) abandoned; "
                f"started_at={row['started_at']}"
            ),
        )


def count_ai_video_shots(shots: list[dict]) -> int:
    """Count ai_video shots for cost projection."""
    return sum(1 for s in shots if s.get("kind") == "ai_video")


def _script_dict_from_row(row) -> dict:
    script = dict(row)
    script["shots"] = json.loads(script["shots_json"])
    return script


def _pending_scripts_for_render(repo: Repository, limit: int) -> list[dict]:
    return [_script_dict_from_row(r) for r in repo.pending_scripts(limit)]


def _persist_rendered_clip(
    repo: Repository,
    script: dict,
    output_path: Path,
    *,
    duration_s: float,
) -> None:
    narration = script.get("narration", "")
    words = narration.strip().split()
    hook = " ".join(words[:5]) if words else script["title"]
    clip_id = script["script_id"]
    repo.insert_clip(
        clip_id=clip_id,
        video_id=None,
        start_s=0.0,
        end_s=float(duration_s),
        hook=hook,
        suggested_title=script["title"],
        title_slug=title_slug(script["title"], clip_id),
        selection_method="ai_generated",
        content_kind="ai_generated",
        script_id=clip_id,
        status="rendered",
        output_path=str(output_path),
    )


_ENCODER_FAILURE_MARKERS = (
    "h264_nvenc",
    "nvenc",
    "no nvenc capable devices",
    "cannot load nvcuda",
    "error initializing output stream",
    "encoder",
)


def _is_encoder_failure(stderr: str) -> bool:
    lower = stderr.lower()
    return any(marker in lower for marker in _ENCODER_FAILURE_MARKERS)


def _log_assembly_failure(cfg, clip_id: str, result) -> None:
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    tail = (result.stderr or "")[-4000:]
    failure_log = logs_dir / f"assembly_fail_{clip_id}.log"
    failure_log.write_text(tail, encoding="utf-8")
    append_alert(
        logs_dir,
        "assembly_failed",
        f"clip {clip_id}: ffmpeg rc={result.returncode}; see {failure_log.name}",
    )


def _run_assembly(
    *,
    cfg,
    clip_id: str,
    concat_list: Path,
    narration_mp3: Path,
    tmp_output: Path,
    total_duration_s: float,
    music_path: Path | None,
    ass_path: Path,
    shot_paths: list[Path],
    asm_cfg,
    durations: list[float],
    video_codec: str = "h264_nvenc",
):
    resolution = tuple(cfg.output_resolution)
    fps = int(getattr(cfg, "output_fps", 30))
    multi_shot = len(shot_paths) > 1
    return run_ffmpeg(
        build_assembler_argv(
            concat_list,
            narration_mp3,
            tmp_output,
            total_duration_s=float(total_duration_s),
            music_path=music_path,
            ass_path=ass_path,
            music_volume_db=float(cfg.music_volume_db),
            loudness_target_lufs=float(cfg.loudness_target_lufs),
            nvenc_preset=cfg.nvenc_preset,
            nvenc_cq=int(cfg.nvenc_cq),
            shot_paths=shot_paths if multi_shot else None,
            crossfade_enabled=asm_cfg.crossfade_enabled,
            crossfade_duration_s=float(asm_cfg.crossfade_duration_s),
            shot_durations_s=durations,
            resolution=resolution,
            fps=fps,
            video_codec=video_codec,
        ),
        tmp_output,
    )


def _ken_burns_render_shot(cfg, duration_s: float, index: int):
    """Build the Ken Burns fallback renderer for one shot (ADR-0009: retained
    as the fallback motion path when image-to-video is unavailable)."""

    def _render(image_path: Path, dest: Path) -> Path:
        tmp = dest.with_suffix(".tmp.mp4")
        argv = build_ken_burns_argv(
            image_path,
            tmp,
            duration_s=duration_s,
            resolution=tuple(cfg.output_resolution),
            zoom_rate=float(getattr(cfg, "ken_burns_zoom_rate", 0.0015)),
            gradient_luma_max=int(getattr(cfg, "ken_burns_gradient_luma_max", 45)),
            gradient_saturation_max=float(
                getattr(cfg, "ken_burns_gradient_saturation_max", 0.35)
            ),
            nvenc_preset=cfg.nvenc_preset,
            nvenc_cq=int(cfg.nvenc_cq),
        )
        result = run_ffmpeg(argv, tmp)
        if result.returncode != 0 or result.output_size_bytes == 0:
            if tmp.exists():
                tmp.unlink()
            raise RuntimeError(f"Ken Burns render failed for shot {index}")
        os.replace(tmp, dest)
        return dest

    return _render


def _render_real_image_shot(
    shot: dict,
    index: int,
    shots_dir: Path,
    cfg,
    *,
    repo: Repository | None = None,
    script_id: str | None = None,
    openrouter_api_key: str | None = None,
) -> Path:
    """Render one real-image Shot: animate its already-resolved still via
    image-to-video (ADR-0009 step 2), falling back to Ken Burns when
    image-to-video is unavailable or unconfigured. The still-SOURCING
    decision (licensed vs. degrade) already happened upstream in
    resolve_shot_plan / resolve_licensed_image — this function only
    animates the still it is handed."""
    cached = shot.get("image_asset")
    if cached is not None:
        image_path = Path(cached.path)
    else:
        entity = shot["entity"]
        query = shot.get("search_query")
        asset = fetch_image(entity, query, cfg)
        image_path = Path(asset.path)

    dest = shots_dir / f"shot_{index:02d}.mp4"
    duration_s = float(shot.get("duration_s", 4))
    ken_burns_render = _ken_burns_render_shot(cfg, duration_s, index)

    ai_cfg = cfg.ai_gen
    video_provider = None
    if openrouter_api_key:
        video_provider = OpenRouterSeedanceClient(
            api_key=openrouter_api_key,
            model=ai_cfg.seedance_model,
            rate_cents_per_second=ai_cfg.seedance_rate_cents_per_second,
        )

    if video_provider is not None:
        entity_name = shot.get("entity", "")
        prompt = f"cinematic product shot, {entity_name}".strip(", ")
        video_cost_estimate = math.ceil(
            duration_s * ai_cfg.seedance_rate_cents_per_second
        )
        try:
            # INV-2: combined (still + video) per-Clip spend checked BEFORE
            # this billable call — never after.
            check_combined_clip_ceiling(
                repo, script_id, ai_cfg.per_clip_cost_cents_max, video_cost_estimate,
            )
            external_id = video_provider.submit(
                prompt, duration_s=int(duration_s), aspect_ratio="9:16",
                first_frame_path=image_path,
            )
            result = video_provider.wait_for_completion(external_id)
            if result.status == GenerationStatus.SUCCEEDED and result.download_url:
                tmp = dest.with_suffix(".tmp.mp4")
                video_provider.download(result.download_url, tmp)
                if repo is not None and script_id and result.cost_cents:
                    repo.quota_record(
                        "openrouter", result.cost_cents, provider="openrouter",
                        script_id=script_id,
                    )
                os.replace(tmp, dest)
                return dest
            logger.warning(
                "seedance i2v failed for shot {}: {}; falling back to Ken Burns",
                index, result.error,
            )
        except UnsupportedFirstFrameError:
            logger.info(
                "seedance: image-to-video unavailable for shot {}; "
                "Ken Burns fallback", index,
            )
        except ClipCostCeilingError:
            raise

    return ken_burns_render(image_path, dest)


def _generate_clip(
    script: dict,
    cfg,
    repo: Repository,
    *,
    openrouter_api_key: str | None,
    dry_run: bool,
    resolved_shots: list[dict] | None = None,
) -> Path | None:
    """Run hybrid shot routing → narration → assemble for one script."""
    clip_id = script.get("script_id", str(uuid.uuid4())[:8])
    title = script.get("title", "untitled")
    narration_text = script.get("narration", "")
    shots_raw = script.get("shots", [])

    ai_cfg = cfg.ai_gen
    narr_cfg = cfg.narration
    asm_cfg = cfg.assembler
    style_suffix = ai_cfg.style_suffix if ai_cfg.style_suffix else ""
    if resolved_shots is not None:
        resolved = resolved_shots
        billable_ai = sum(1 for s in resolved if s.get("kind") == "ai_video")
    else:
        normalized = normalize_shots(shots_raw)
        resolved, billable_ai = resolve_shot_plan(
            normalized,
            licensed_resolver=lambda entity, query: resolve_licensed_image(
                entity, query, cfg,
            ),
        )

    if billable_ai * 67 > ai_cfg.per_clip_cost_cents_max and billable_ai > 0:
        raise RuntimeError(
            f"clip {clip_id} projected OpenRouter cost "
            f"{billable_ai * 67}c exceeds per_clip_cost_cents_max="
            f"{ai_cfg.per_clip_cost_cents_max} ({billable_ai} ai_video shots)"
        )

    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = cfg.abs_path(f"data/ai_gen/{clip_id}")
    shots_dir.mkdir(parents=True, exist_ok=True)
    narration_dir = Path(tempfile.mkdtemp(prefix=f"gen_{clip_id}_narr_"))
    subs_dir = Path(tempfile.mkdtemp(prefix=f"gen_{clip_id}_subs_"))

    slug = title_slug(title, clip_id)
    output_path = pending_dir / f"__unscheduled__{clip_id}__{slug}.mp4"

    if dry_run:
        logger.info("[dry-run] skipping ai_gen + narration + assemble for {}", clip_id)
        return None

    ai_shots = [
        {
            **s,
            "prompt": f"{s['prompt']}, {style_suffix}".strip(", "),
        }
        for s in resolved
        if s.get("kind") == "ai_video"
    ]
    ai_paths: list[Path] = []
    if ai_shots:
        track_quota = isinstance(repo, Repository)
        if track_quota:
            # Issue 62 / INV-1 — check the rolling 7x24h OpenRouter ceiling
            # BEFORE issuing the billable call. A call that would cross it is
            # refused, not attempted: zero provider calls, no partial charge.
            weekly_ceiling = getattr(ai_cfg, "weekly_spend_cents_ceiling", 800)
            projected_cents = len(ai_shots) * DEFAULT_SHOT_COST_ESTIMATE_CENTS
            if repo.quota_would_exceed_week(
                projected_cents, weekly_ceiling, provider="openrouter",
            ):
                raise SpendCapReached(
                    f"clip {clip_id}: projected OpenRouter cost {projected_cents}c "
                    f"would push the rolling 7d total "
                    f"({repo.quota_rolling_week_total(provider='openrouter')}c) past "
                    f"weekly_spend_cents_ceiling={weekly_ceiling}c"
                )
        if not openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY required for ai_video shots")
        client = OpenRouterKlingClient(api_key=openrouter_api_key)
        ai_paths = generate_shots(
            ai_shots, shots_dir, client,
            max_concurrent=ai_cfg.max_concurrent,
            repo=repo if track_quota else None,
            script_id=clip_id if track_quota else None,
            per_clip_cost_cents_max=ai_cfg.per_clip_cost_cents_max if track_quota else None,
        )
        if track_quota:
            if repo.quota_script_total(clip_id) > ai_cfg.per_clip_cost_cents_max:
                raise RuntimeError(
                    f"clip {clip_id} cumulative OpenRouter cost "
                    f"{repo.quota_script_total(clip_id)}c exceeds "
                    f"per_clip_cost_cents_max={ai_cfg.per_clip_cost_cents_max}"
                )
            if repo.quota_today_total(provider="openrouter") > ai_cfg.daily_spend_cents_ceiling:
                raise RuntimeError(
                    f"daily OpenRouter spend exceeds ceiling "
                    f"{ai_cfg.daily_spend_cents_ceiling}c"
                )

    shot_paths: list[Path] = []
    ai_idx = 0
    for i, shot in enumerate(resolved):
        if shot.get("kind") == "real_image":
            shot_paths.append(
                _render_real_image_shot(
                    shot, i, shots_dir, cfg,
                    repo=repo, script_id=clip_id,
                    openrouter_api_key=openrouter_api_key,
                )
            )
        else:
            shot_paths.append(ai_paths[ai_idx])
            ai_idx += 1

    narration_mp3 = narration_dir / f"{clip_id}_narration.mp3"
    synthesize(
        narration_text,
        narration_mp3,
        voice=narr_cfg.voice,
        rate=narr_cfg.rate,
        pitch=narr_cfg.pitch,
        engine=narr_cfg.engine,
        kokoro_voice=narr_cfg.kokoro_voice,
    )

    word_timings = align(narration_mp3)
    ass_path = subs_dir / f"{clip_id}_subs.ass"
    write_line_ass_file(ass_path, word_timings)

    with tempfile.TemporaryDirectory(prefix=f"gen_{clip_id}_build_") as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        write_concat_list(shot_paths, concat_list)
        durations = [float(s.get("duration_s", 4)) for s in resolved]
        if asm_cfg.crossfade_enabled and len(shot_paths) > 1:
            total_duration_s = sum(durations) - asm_cfg.crossfade_duration_s * (len(durations) - 1)
        else:
            total_duration_s = sum(durations)
        tmp_output = output_path.with_suffix(".tmp.mp4")

        music_dir = cfg.abs_path("data/music")
        music_path: Path | None = None
        if music_dir.exists():
            tracks = sorted(
                f for f in music_dir.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            )
            music_path = tracks[0] if tracks else None

        result = _run_assembly(
            cfg=cfg,
            clip_id=clip_id,
            concat_list=concat_list,
            narration_mp3=narration_mp3,
            tmp_output=tmp_output,
            total_duration_s=total_duration_s,
            music_path=music_path,
            ass_path=ass_path,
            shot_paths=shot_paths,
            asm_cfg=asm_cfg,
            durations=durations,
        )

        if result.returncode != 0 or result.output_size_bytes == 0:
            if _is_encoder_failure(result.stderr or ""):
                logger.warning("NVENC assembly failed for {}; retrying with libx264", clip_id)
                result = _run_assembly(
                    cfg=cfg,
                    clip_id=clip_id,
                    concat_list=concat_list,
                    narration_mp3=narration_mp3,
                    tmp_output=tmp_output,
                    total_duration_s=total_duration_s,
                    music_path=music_path,
                    ass_path=ass_path,
                    shot_paths=shot_paths,
                    asm_cfg=asm_cfg,
                    durations=durations,
                    video_codec="libx264",
                )

    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp_output.exists():
            tmp_output.unlink()
        _log_assembly_failure(cfg, clip_id, result)
        raise RuntimeError(
            f"ffmpeg failed (rc={result.returncode}) for clip {clip_id}"
        )

    os.replace(tmp_output, output_path)
    logger.info("assembled: {}", output_path.name)
    return output_path


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


def run_generation(
    *,
    repo: Repository,
    cfg: Config,
    clips_n: int = 2,
    dry_run: bool = False,
    openrouter_api_key: str | None = None,
    ollama_host: str | None = None,
) -> tuple[bool, dict]:
    """Run the Pivot.6 generation pipeline. Returns (success, summary)."""
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    started_at_utc = datetime.now(timezone.utc)
    run_id = repo.start_run(kind="generation")
    summary: dict[str, Any] = {"stages": {}, "dry_run": dry_run}

    try:
        # --- Batch stages: topic ingest + scripting ---
        logger.info("gen_run: stage=topic_ingest")
        topics = fetch_unscripted_topics(cfg, repo, dry_run=dry_run)
        summary["stages"]["topic_ingest"] = _summarize(topics)

        logger.info("gen_run: stage=scripter_a")
        if dry_run:
            topics_scored = run_stage_a(cfg, repo, scorer_fn=None, tagger_fn=None)
        else:
            model = cfg.ollama_model
            topics_scored = run_stage_a(
                cfg, repo,
                scorer_fn=make_topic_scorer(model),
                tagger_fn=make_topic_tagger(model),
            )
        summary["stages"]["scripter_a"] = _summarize(topics_scored)

        logger.info("gen_run: stage=scripter_b")
        if dry_run:
            scripts = run_stage_b(cfg, repo, topics_scored, generator_fn=None)
        else:
            scripts = run_stage_b(
                cfg, repo, topics_scored,
                generator_fn=make_script_generator(cfg.ollama_model),
                narration_fn=make_narration_generator(cfg.ollama_model),
            )
        summary["stages"]["scripter_b"] = _summarize(scripts)

        logger.info("gen_run: stage=scripter_c")
        if dry_run:
            selected = run_stage_c(cfg, repo, scripts, scorer_fn=None)[:clips_n]
        else:
            selected = run_stage_c(
                cfg, repo, scripts,
                scorer_fn=make_script_scorer(cfg.ollama_model),
            )[:clips_n]
        summary["stages"]["scripter_c"] = _summarize(selected)

        if not selected and not dry_run:
            selected = _pending_scripts_for_render(repo, clips_n)
            if selected:
                logger.info(
                    "gen_run: stage_c returned 0; using {} pending script(s) from backlog",
                    len(selected),
                )

        # --- Per-script: pre-billing policy, resolve shot plan, generate clip ---
        ai_cfg = cfg.ai_gen
        clips_generated = 0
        for script in selected:
            try:
                verdict = evaluate_clip_policy(
                    cfg,
                    script.get("narration", ""),
                    script.get("title", ""),
                )
                if verdict.infrastructure_failed:
                    logger.warning(
                        "gen_run: policy infra failed for {}: {}",
                        script.get("script_id"),
                        verdict.infrastructure_reason,
                    )
                    continue
                if not verdict.passed:
                    logger.info(
                        "gen_run: policy rejected {} — {}",
                        script.get("script_id"),
                        verdict.reason_string,
                    )
                    continue

                shots_raw = script.get("shots", [])
                normalized = normalize_shots(shots_raw)
                resolved, billable_ai = resolve_shot_plan(
                    normalized,
                    licensed_resolver=lambda entity, query: resolve_licensed_image(
                        entity, query, cfg,
                    ),
                )
                if billable_ai * 67 > ai_cfg.per_clip_cost_cents_max and billable_ai > 0:
                    logger.error(
                        "gen_run: clip {} projected OpenRouter cost {}c exceeds cap {}",
                        script.get("script_id"),
                        billable_ai * 67,
                        ai_cfg.per_clip_cost_cents_max,
                    )
                    continue

                durations = [float(s.get("duration_s", 4)) for s in resolved]
                asm_cfg = cfg.assembler
                if asm_cfg.crossfade_enabled and len(resolved) > 1:
                    duration_s = sum(durations) - asm_cfg.crossfade_duration_s * (
                        len(durations) - 1
                    )
                else:
                    duration_s = sum(durations)

                out = _generate_clip(
                    script, cfg, repo,
                    openrouter_api_key=openrouter_api_key,
                    dry_run=dry_run,
                    resolved_shots=resolved,
                )
                if out and not dry_run:
                    _persist_rendered_clip(
                        repo, script, out, duration_s=duration_s,
                    )
                clips_generated += 1
            except SpendCapReached as exc:
                # Issue 62 / INV-1 — a budget stop is a normal outcome, not a
                # failure: refuse the remaining calls, alert, and finish the
                # run success=1 with a capped summary rather than raising.
                logger.warning("gen_run: {}", exc)
                append_alert(logs_dir, kind="spend_cap_reached", message=str(exc))
                summary["capped"] = True
                summary["capped_reason"] = str(exc)
                break
            except OpenRouterAuthError as exc:
                # Issue 61 / INV-12 — an invalid key will never succeed on
                # retry, so this aborts the whole run rather than moving to the
                # next script. Distinct from the transient-failure path and from
                # the spend cap: this is a genuine failure, so we alert and
                # re-raise, letting the outer handler finalize the run
                # success=0. str(exc) carries no key material (INV-6).
                logger.error("gen_run: OpenRouter auth failed: {}", exc)
                append_alert(logs_dir, kind="auth_failed", message=str(exc))
                summary["auth_failed"] = True
                raise
            except ImageFetchError as exc:
                logger.error(
                    "gen_run: image fetch failed for {}: {}",
                    script.get("script_id"), exc,
                )
            except Exception as exc:
                logger.error("gen_run: clip generation failed for {}: {}", script.get("script_id"), exc)
        summary["stages"]["generate_clips"] = {"count": clips_generated}

        # --- Batch stages: screen + slot + retain ---
        logger.info("gen_run: stage=quality_screen")
        qs_results = quality_screen.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["quality_screen"] = _summarize(qs_results)

        logger.info("gen_run: stage=slot_planner")
        sp_results = slot_planner.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["slot_planner"] = _summarize(sp_results)

        logger.info("gen_run: stage=retention")
        ret_results = retention.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["retention"] = _summarize(ret_results)

        repo.finish_run(run_id, success=True, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="gen_run_finished",
            message=f"gen_run finished; stages={list(summary['stages'].keys())}",
        )
        append_run_row(
            logs_dir, kind="generation",
            started_at=started_at_utc, finished_at=datetime.now(timezone.utc),
            success=True, summary=_build_runs_md_summary(summary),
        )

    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        repo.finish_run(run_id, success=False, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="gen_run_failed",
            message=summary["error"],
        )
        append_run_row(
            logs_dir, kind="generation",
            started_at=started_at_utc, finished_at=datetime.now(timezone.utc),
            success=False, summary=_build_runs_md_summary(summary),
        )
        raise

    return (True, summary)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.gen_run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clips", type=int, default=2, dest="clips_n")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    load_env_file()
    cfg = load_config(args.config)
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    setup_logging(logs_dir)

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(f"state.db not found at {db_path}. Run bootstrap --init-db first.")
        return 1

    lock_path = cfg.abs_path("data/.gen_run.lock")
    try:
        with acquire_run_lock(lock_path):
            conn = connect(db_path)
            repo = Repository(conn)
            try:
                sweep_abandoned_runs(repo, cfg, logs_dir)
                check_liveness(repo, cfg, logs_dir)
                openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
                ollama_host = os.environ.get("OLLAMA_HOST")
                success, summary = run_generation(
                    repo=repo, cfg=cfg, clips_n=args.clips_n,
                    dry_run=args.dry_run,
                    openrouter_api_key=openrouter_api_key,
                    ollama_host=ollama_host,
                )
                print(json.dumps(summary, indent=2))
                return 0 if success else 1
            except Exception:
                return 1
            finally:
                conn.close()
    except RunLockHeld:
        append_alert(
            logs_dir, kind="lock_held",
            message="gen_run skipped: another instance holds data/.gen_run.lock",
        )
        logger.warning("gen_run: lock_held; another instance is running")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
