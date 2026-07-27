"""Image-first shot routing ladder (ADR-0009 / Issue 66).

Per Shot, in order:

  1. **Source the still.**
     - Shot names a real entity (``kind == "real_image"``) -> attempt the
       Licensed source lookup FIRST (INV-7: a Generated still may never
       pre-empt a Licensed source that would have resolved). Hit -> still
       sourced, rung tentatively ``licensed_i2v``. Miss -> fall through to
       Generated still.
     - Shot names no real entity, or the licensed lookup missed -> Generated
       still via the configured ``StillProvider`` (Issue 64), rung
       tentatively ``generated_i2v``.
     - The still-generation step failing entirely (any exception, including
       INV-3's own per-still/per-clip ceiling) -> no still at all; rung
       degrades to ``text_to_video``.
  2. **Animate.** The still (licensed or generated) is passed as
     ``first_frame_path`` to the configured video ``Provider``.
     - ``UnsupportedFirstFrameError`` (image-to-video unavailable) -> Ken
       Burns fallback (``src/assembler/ken_burns.py`` — retained, not
       deleted); rung becomes ``ken_burns``.
     - No still available at all -> text-to-video (``first_frame_path=None``);
       rung stays ``text_to_video``.
  3. **INV-2** — before EVERY billable call (still generation, video
     submission — retries included), the Clip's COMBINED OpenRouter spend
     (``Repository.quota_script_total`` sums both the ``openrouter`` video
     bucket and the ``openrouter_still`` still bucket for one ``script_id``)
     is checked against ``per_clip_cost_cents_max``. Refused BEFORE the
     call, never after — zero provider calls, no partial charge.
  4. **INV-8** — any shot naming/depicting a living person is rejected
     before any billable call, checked first of all.

Directed scripts (ADR-0008) hand this function ordinary shot dicts with the
same schema everything else does; there is no director-specific branch here,
so a Directed script's shots traverse the identical ladder.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.ai_gen.base import GenerationStatus, Provider, UnsupportedFirstFrameError
from src.image_fetch.base import ImageAsset
from src.image_fetch.fetcher import _reject_living_person
from src.image_gen.base import StillProvider

LicensedResolver = Callable[[str, str | None], ImageAsset | None]
KenBurnsRenderer = Callable[[Path, Path], Path]

RUNG_LICENSED_I2V = "licensed_i2v"
RUNG_GENERATED_I2V = "generated_i2v"
RUNG_TEXT_TO_VIDEO = "text_to_video"
RUNG_KEN_BURNS = "ken_burns"

DEFAULT_VIDEO_COST_ESTIMATE_CENTS = 67
DEFAULT_STILL_COST_ESTIMATE_CENTS = 1


class ClipCostCeilingError(RuntimeError):
    """INV-2: raised before a billable call (still OR video) that would push
    a Clip's COMBINED OpenRouter spend past per_clip_cost_cents_max. Always
    raised BEFORE the call — zero provider calls, no partial charge."""


@dataclass
class RoutedShot:
    rung: str
    path: Path
    still_path: Path | None = None
    image_asset: ImageAsset | None = None


def check_combined_clip_ceiling(
    repo,
    script_id: str | None,
    per_clip_cost_cents_max: int | None,
    projected_cents: int,
) -> None:
    """INV-2: refuse a billable call BEFORE it happens if the Clip's
    combined (still + video) OpenRouter spend would cross the cap.

    ``Repository.quota_script_total`` sums ALL ``provider='openrouter'``
    rows for a script_id regardless of ``endpoint`` — it already includes
    both the ``openrouter`` (video) and ``openrouter_still`` (still)
    buckets, so this one check covers both kinds of billable call.
    """
    if repo is None or script_id is None or per_clip_cost_cents_max is None:
        return
    current = repo.quota_script_total(script_id)
    if current + projected_cents > per_clip_cost_cents_max:
        raise ClipCostCeilingError(
            f"clip {script_id} combined OpenRouter spend {current}c + "
            f"projected {projected_cents}c would exceed "
            f"per_clip_cost_cents_max={per_clip_cost_cents_max}"
        )


def _shot_text(shot: dict) -> tuple[str | None, str]:
    entity = shot.get("entity")
    prompt = shot.get("prompt") or (
        f"cinematic tech b-roll, {entity}" if entity else ""
    )
    return entity, prompt


def route_shot(
    shot: dict,
    index: int,
    dest_dir: Path,
    *,
    licensed_resolver: LicensedResolver | None,
    still_provider: StillProvider | None,
    video_provider: Provider,
    ken_burns_render: KenBurnsRenderer,
    living_person_patterns: list[str] | None = None,
    script_id: str | None = None,
    repo=None,
    per_clip_cost_cents_max: int | None = None,
    still_cost_estimate_cents: int = DEFAULT_STILL_COST_ESTIMATE_CENTS,
    video_cost_estimate_cents: int | None = None,
    poll_interval_s: int = 15,
    timeout_s: int = 600,
    aspect_ratio: str = "9:16",
) -> RoutedShot:
    """Route and render exactly one Shot through the image-first ladder.

    Every dependency (licensed lookup, still generator, video provider, Ken
    Burns renderer) is injected so this function never performs real
    network I/O itself — tests drive it with fakes (no real spend).
    """
    entity, prompt = _shot_text(shot)
    duration_s = int(shot.get("duration_s", 4))
    query = shot.get("search_query")
    video_cost_estimate = (
        video_cost_estimate_cents
        if video_cost_estimate_cents is not None
        else math.ceil(duration_s * (DEFAULT_VIDEO_COST_ESTIMATE_CENTS / 4))
    )

    # INV-8: reject before ANY billable call — checked first of all.
    _reject_living_person(entity or prompt, living_person_patterns or [])

    still_path: Path | None = None
    image_asset: ImageAsset | None = None
    rung = RUNG_TEXT_TO_VIDEO

    # --- Step 1: source the still --------------------------------------
    if shot.get("kind") == "real_image" and entity:
        # INV-7: the Licensed source lookup MUST be attempted, and observed
        # to miss, before a Generated still is ever considered. This is the
        # ordering the ticket requires be enforced by code, not prompt
        # discipline — it is a plain sequential call, nothing races it.
        image_asset = licensed_resolver(entity, query) if licensed_resolver else None
        if image_asset is not None:
            still_path = Path(image_asset.path)
            rung = RUNG_LICENSED_I2V

    if still_path is None and still_provider is not None:
        try:
            check_combined_clip_ceiling(
                repo, script_id, per_clip_cost_cents_max, still_cost_estimate_cents,
            )
            still_dest = dest_dir / f"shot_{index:02d}_still.png"
            still_result = still_provider.generate(
                prompt, aspect_ratio=aspect_ratio, dest=still_dest,
                script_id=script_id,
            )
            still_path = Path(still_result.path)
            rung = RUNG_GENERATED_I2V
        except Exception:
            # Still step failed entirely (ceiling, auth, network, ...) ->
            # degrade to text-to-video exactly as ADR-0009 specifies.
            still_path = None
            rung = RUNG_TEXT_TO_VIDEO

    dest = dest_dir / f"shot_{index:02d}.mp4"

    # --- Step 2: animate -------------------------------------------------
    if still_path is not None:
        try:
            check_combined_clip_ceiling(
                repo, script_id, per_clip_cost_cents_max, video_cost_estimate,
            )
            external_id = video_provider.submit(
                prompt, duration_s=duration_s, aspect_ratio=aspect_ratio,
                first_frame_path=still_path,
            )
        except UnsupportedFirstFrameError:
            path = ken_burns_render(still_path, dest)
            return RoutedShot(
                rung=RUNG_KEN_BURNS, path=path, still_path=still_path,
                image_asset=image_asset,
            )
        _wait_and_download(
            video_provider, external_id, dest, index,
            repo=repo, script_id=script_id,
            poll_interval_s=poll_interval_s, timeout_s=timeout_s,
        )
        return RoutedShot(
            rung=rung, path=dest, still_path=still_path, image_asset=image_asset,
        )

    # --- Step 3: text-to-video fallback (no still at all) -----------------
    check_combined_clip_ceiling(
        repo, script_id, per_clip_cost_cents_max, video_cost_estimate,
    )
    external_id = video_provider.submit(
        prompt, duration_s=duration_s, aspect_ratio=aspect_ratio,
        first_frame_path=None,
    )
    _wait_and_download(
        video_provider, external_id, dest, index,
        repo=repo, script_id=script_id,
        poll_interval_s=poll_interval_s, timeout_s=timeout_s,
    )
    return RoutedShot(rung=RUNG_TEXT_TO_VIDEO, path=dest, still_path=None)


def _wait_and_download(
    video_provider: Provider,
    external_id: str,
    dest: Path,
    index: int,
    *,
    repo,
    script_id: str | None,
    poll_interval_s: int,
    timeout_s: int,
) -> None:
    result = video_provider.wait_for_completion(
        external_id, poll_interval_s=poll_interval_s, timeout_s=timeout_s,
    )
    if result.status != GenerationStatus.SUCCEEDED or not result.download_url:
        raise RuntimeError(
            f"route_shot: video generation failed for shot {index}: {result.error}"
        )
    video_provider.download(result.download_url, dest)
    if repo is not None and script_id and result.cost_cents:
        repo.quota_record(
            "openrouter", result.cost_cents, provider="openrouter",
            script_id=script_id,
        )


def route_shots(
    shots: list[dict],
    dest_dir: Path,
    **kwargs,
) -> list[RoutedShot]:
    """Route every Shot of a Clip in order, and persist the rung each Shot
    took to ``dest_dir/routing.json`` — readable evidence of the ladder
    decision independent of any in-memory assertion."""
    routed = [route_shot(shot, i, dest_dir, **kwargs) for i, shot in enumerate(shots)]
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest = dest_dir / "routing.json"
    manifest.write_text(
        json.dumps(
            [
                {"index": i, "rung": r.rung, "path": str(r.path)}
                for i, r in enumerate(routed)
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return routed
