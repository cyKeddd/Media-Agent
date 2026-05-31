"""Backfill-gate legacy unscripted topics (Issue 39)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from loguru import logger

from src.topic_ingest.niche_gate import NicheVerdict, classify_niche


@dataclass(frozen=True)
class BackfillResult:
    kept: int
    rejected: int
    infra_skipped: int


def backfill_unscripted_topics(
    cfg,
    repo,
    *,
    _classify: Callable[..., NicheVerdict] | None = None,
    dry_run: bool = False,
) -> BackfillResult:
    """Classify all ``unscripted`` topics; reject off-niche legacy backlog."""
    classify = _classify or classify_niche
    model = getattr(cfg, "ollama_model", "qwen2.5:3b-instruct")

    kept = rejected = infra_skipped = 0

    for row in repo.unscripted_topics():
        title = row["title"]
        summary = row["summary"]
        topic_id = row["id"]

        verdict = classify(title, summary, model=model)

        if verdict.infrastructure_failed:
            infra_skipped += 1
            kept += 1
            continue

        if verdict.is_on_niche:
            kept += 1
            continue

        rejected += 1
        logger.debug(
            "backfill: rejected_off_niche id={} — {} — {}",
            topic_id,
            verdict.reason,
            title,
        )
        if not dry_run:
            repo.mark_topic_rejected_off_niche(topic_id)

    logger.info(
        "backfill complete: kept={} rejected={} infra_skipped={}{}",
        kept,
        rejected,
        infra_skipped,
        " (dry-run)" if dry_run else "",
    )
    return BackfillResult(kept=kept, rejected=rejected, infra_skipped=infra_skipped)
