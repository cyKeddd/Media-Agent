"""Per-script shot generator — submits N shots concurrently and downloads results.

Usage (from weekly_run / gen_run):
    from src.ai_gen.runner import generate_shots
    shot_paths = generate_shots(shots, dest_dir, client, poll_interval_s=15)
"""

from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .base import GenerationStatus, Provider

DEFAULT_SHOT_COST_ESTIMATE_CENTS = 67


@dataclass
class ShotJob:
    index: int
    prompt: str
    duration_s: int
    external_id: str | None = None
    output_path: Path | None = None
    error: str | None = None
    cost_cents: int | None = None
    reused: bool = False
    job_id: str | None = None


def generate_shots(
    shots: list[dict],
    dest_dir: Path,
    client: Provider,
    *,
    aspect_ratio: str = "9:16",
    poll_interval_s: int = 15,
    timeout_s: int = 600,
    max_concurrent: int = 2,
    repo=None,
    script_id: str | None = None,
    per_clip_cost_cents_max: int | None = None,
    shot_cost_estimate_cents: int = DEFAULT_SHOT_COST_ESTIMATE_CENTS,
) -> list[Path]:
    """Submit all shots, poll until done, download mp4s, return ordered paths.

    When ``script_id`` and ``repo`` are set, succeeded ``generation_jobs`` are
    reused on retry (0¢ re-bill) and OpenRouter spend is attributed cumulatively.

    ``shot_cost_estimate_cents`` (Issue 67) is the PRE-billing per-shot cost
    projection used by the ceiling check below, before any provider call is
    made. Callers with a config-driven provider should derive this from
    ``src.ai_gen.factory.estimate_shot_cost_cents`` rather than relying on
    the flat ``DEFAULT_SHOT_COST_ESTIMATE_CENTS`` default, which is tuned
    for Kling and over-estimates a per-second-billed provider like Seedance.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[ShotJob] = [
        ShotJob(
            index=i,
            prompt=s["prompt"],
            duration_s=s.get("duration_s", 5),
            job_id=str(uuid.uuid4()),
        )
        for i, s in enumerate(shots)
    ]

    reuse_paths: dict[int, Path] = {}
    if repo is not None and script_id:
        for row in repo.succeeded_generation_jobs(script_id):
            src = row["output_path"]
            if src and Path(src).exists():
                reuse_paths[int(row["shot_index"])] = Path(src)

    for job in jobs:
        if job.index in reuse_paths:
            src = reuse_paths[job.index]
            dest = dest_dir / f"shot_{job.index:02d}.mp4"
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
                job.output_path = dest
            else:
                job.output_path = src
            job.reused = True
            logger.info(
                "ai_gen: reusing shot {} for {} → {}",
                job.index, script_id, job.output_path,
            )

    billable = [j for j in jobs if not j.reused]
    if billable:
        _check_script_ceiling(
            repo, script_id, billable, per_clip_cost_cents_max,
            shot_cost_estimate_cents,
        )
        _submit_all(billable, client, aspect_ratio, max_concurrent)
        _wait_and_download(billable, client, dest_dir, poll_interval_s, timeout_s)

    failed = [j for j in jobs if j.error]
    if failed:
        errs = "; ".join(f"shot {j.index}: {j.error}" for j in failed)
        raise RuntimeError(f"generate_shots: {len(failed)} shot(s) failed — {errs}")

    if repo is not None:
        for job in jobs:
            if job.reused:
                continue
            if job.cost_cents:
                if script_id and repo.quota_would_exceed_script(
                    script_id, job.cost_cents, per_clip_cost_cents_max or 0,
                ) and per_clip_cost_cents_max:
                    raise RuntimeError(
                        f"generate_shots: clip {script_id} OpenRouter cost "
                        f"{repo.quota_script_total(script_id) + job.cost_cents}c exceeds "
                        f"per_clip_cost_cents_max={per_clip_cost_cents_max}"
                    )
                # Record spend unconditionally so the weekly/daily ledgers are
                # populated even when the caller has no script_id to attribute
                # to yet — a cap that reads an empty ledger never fires.
                repo.quota_record(
                    "openrouter",
                    job.cost_cents,
                    provider="openrouter",
                    script_id=script_id,
                )
            if script_id:
                repo.upsert_generation_job(
                    job_id=job.job_id or str(uuid.uuid4()),
                    script_id=script_id,
                    shot_index=job.index,
                    provider="openrouter_kling",
                    prompt=job.prompt,
                    duration_s=job.duration_s,
                    status="succeeded" if job.output_path else "failed",
                    external_id=job.external_id,
                    output_path=str(job.output_path) if job.output_path else None,
                    cost_cents=job.cost_cents,
                    error=job.error,
                )

    return [j.output_path for j in jobs]  # type: ignore[return-value]


def _check_script_ceiling(
    repo,
    script_id: str | None,
    jobs: list[ShotJob],
    per_clip_cost_cents_max: int | None,
    shot_cost_estimate_cents: int = DEFAULT_SHOT_COST_ESTIMATE_CENTS,
) -> None:
    if repo is None or not script_id or not per_clip_cost_cents_max:
        return
    projected = repo.quota_script_total(script_id) + (
        len(jobs) * shot_cost_estimate_cents
    )
    if projected > per_clip_cost_cents_max:
        raise RuntimeError(
            f"generate_shots: clip {script_id} projected OpenRouter cost "
            f"{projected}c exceeds per_clip_cost_cents_max={per_clip_cost_cents_max}"
        )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _submit_all(
    jobs: list[ShotJob], client: Provider, aspect_ratio: str, max_concurrent: int
) -> None:
    semaphore = threading.Semaphore(max_concurrent)

    def submit_one(job: ShotJob) -> None:
        with semaphore:
            try:
                job.external_id = client.submit(
                    job.prompt,
                    duration_s=job.duration_s,
                    aspect_ratio=aspect_ratio,
                )
                logger.info(
                    "ai_gen: submitted shot {} → external_id={}", job.index, job.external_id
                )
            except Exception as exc:
                job.error = str(exc)
                logger.error("ai_gen: shot {} submit failed: {}", job.index, exc)

    threads = [threading.Thread(target=submit_one, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _wait_and_download(
    jobs: list[ShotJob],
    client: Provider,
    dest_dir: Path,
    poll_interval_s: int,
    timeout_s: int,
) -> None:
    pending = [j for j in jobs if j.external_id and not j.error]

    def process_one(job: ShotJob) -> None:
        try:
            result = client.wait_for_completion(
                job.external_id,  # type: ignore[arg-type]
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
            )
            if result.status == GenerationStatus.SUCCEEDED and result.download_url:
                dest = dest_dir / f"shot_{job.index:02d}.mp4"
                client.download(result.download_url, dest)
                job.output_path = dest
                job.cost_cents = result.cost_cents
                logger.info("ai_gen: shot {} downloaded → {}", job.index, dest)
            else:
                job.error = result.error or "unknown failure"
                logger.error("ai_gen: shot {} failed: {}", job.index, job.error)
        except Exception as exc:
            job.error = str(exc)
            logger.error("ai_gen: shot {} error during wait/download: {}", job.index, exc)

    threads = [threading.Thread(target=process_one, args=(j,)) for j in pending]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
