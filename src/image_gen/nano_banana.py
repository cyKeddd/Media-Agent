"""OpenRouter Nano Banana 2 (google/gemini-3.1-flash-image) still provider.

ADR-0009: every Shot is generated image-first (a Generated still), then
animated by a video Provider (src/ai_gen/base.py) via first_frame_path.
This is the concrete StillProvider (src/image_gen/base.py) landing in
Issue 64.

API shape assumed (NOT verified against the live endpoint — tests in
tests/test_nano_banana_provider.py drive a fake HTTP layer only):

  POST https://openrouter.ai/api/v1/images
  body:     {"model": "google/gemini-3.1-flash-image",
             "prompt": "<prompt>, <style suffix>",
             "size": "1080x1920"}
  response: {"data": [{"b64_json": "<base64 png>"}],
             "usage": {"cost": 0.004}}

This mirrors the "usage.cost" convention OpenRouterKlingClient already
relies on (openrouter_kling.py) and OpenRouter's documented images
response shape (a `data` array of image objects), extended with a
`b64_json` field analogous to OpenAI's images API — the closest documented
precedent for an image-generation response on OpenRouter as of 2026-07-27.
If the live endpoint differs, only _extract_image_b64 / the request body
in generate() need to change; the retry/auth/cost-ceiling/quota plumbing
around it does not depend on the exact shape.

Style suffix (ADR-0009 — "all four stills of a Clip share a look"): reuses
the SAME config field and concatenation pattern gen_run._generate_clip
already applies to ai_video shot prompts
(``f"{prompt}, {style_suffix}".strip(", ")`` against ``ai_gen.style_suffix``,
see src/gen_run.py) — no second style mechanism is introduced here. The
caller passes ``ai_cfg.style_suffix`` in as ``style_suffix=``.

No-living-individuals check (INV-8): reuses
``src.image_fetch.fetcher._reject_living_person`` against
``Config.image_fetch.living_person_patterns`` — the same gate real_image
licensed sourcing already enforces (src/image_fetch/fetcher.py). No second
check is written here; the caller passes
``cfg.image_fetch.living_person_patterns`` in as ``living_person_patterns=``.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.ai_gen.base import OpenRouterAuthError
from src.image_fetch.fetcher import _reject_living_person

from .base import StillProvider, StillResult

_BASE_URL = "https://openrouter.ai/api/v1"

# ADR-0002: Shot normalization conforms every Shot to 1080x1920 before
# stitching; a still narrower than that on its short edge would need to be
# upscaled. Requesting this size directly avoids that.
STILL_WIDTH = 1080
STILL_HEIGHT = 1920
STILL_SIZE = f"{STILL_WIDTH}x{STILL_HEIGHT}"

# ADR-0009 pricing note (2026-07-27): Nano Banana 2 is ~$0.004/still (0.4c).
# Used only as the pre-call INV-3 projection estimate when the provider's
# real usage.cost is not yet known; the real cost from the response always
# overrides it in the recorded quota_usage row and the returned StillResult.
DEFAULT_STILL_COST_ESTIMATE_CENTS = 1


class StillCostCeilingError(RuntimeError):
    """INV-3: raised when a still's projected cost, or a Clip's accumulated
    still spend, would exceed the configured ceilings. Always raised BEFORE
    any HTTP call is made — zero provider calls, no partial charge."""


def _is_retryable(exc: BaseException) -> bool:
    """INV-12: mirrors OpenRouterKlingClient._is_retryable (openrouter_kling.py)
    — 5xx / connection / timeout retry; 401/403 are raised as
    OpenRouterAuthError by _check_response before reaching this predicate
    and are never retried, so an invalid key wastes exactly one attempt."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and 500 <= status < 600
    return False


class NanoBananaProvider(StillProvider):
    """StillProvider backed by OpenRouter's google/gemini-3.1-flash-image."""

    provider_name = "nano_banana"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "google/gemini-3.1-flash-image",
        style_suffix: str = "",
        living_person_patterns: list[str] | None = None,
        still_cost_cents_max: int = 5,
        still_clip_cost_cents_max: int = 20,
        cost_cents_estimate: int = DEFAULT_STILL_COST_ESTIMATE_CENTS,
        repo=None,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self.model = model
        self._style_suffix = style_suffix
        self._living_person_patterns = living_person_patterns or []
        self._still_cost_cents_max = still_cost_cents_max
        self._still_clip_cost_cents_max = still_clip_cost_cents_max
        self._cost_cents_estimate = cost_cents_estimate
        # Issue 62/64: repo carries quota_record + the raw sqlite connection
        # used to sum still-only spend per Clip (see _clip_still_spend).
        self._repo = repo
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # StillProvider interface
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        dest: Path,
        script_id: str | None = None,
    ) -> StillResult:
        """Generate a still image at dest.

        script_id (Issue 64 / INV-2): optional Clip attribution used to
        meter cost into quota_usage and to enforce the INV-3 per-Clip still
        cap. Not part of the StillProvider ABC signature (which callers not
        yet tracking a Clip can still satisfy); the ADR-0009 shot-routing
        wiring (a later ticket) is expected to always pass it.
        """
        # INV-8: reject a prompt naming a living person before any HTTP call.
        _reject_living_person(prompt, self._living_person_patterns)

        # INV-3: refuse a still whose projected cost exceeds the per-still cap.
        if self._cost_cents_estimate > self._still_cost_cents_max:
            raise StillCostCeilingError(
                f"projected still cost {self._cost_cents_estimate}c exceeds "
                f"still_cost_cents_max={self._still_cost_cents_max}"
            )

        # INV-3: refuse when the Clip's accumulated still spend would exceed
        # the per-Clip cap. Isolated from video spend on the same Clip —
        # keyed on endpoint='openrouter_still', a separate bucket from the
        # 150c per-Clip video cap (INV-2).
        if script_id is not None:
            accumulated = self._clip_still_spend(script_id)
            if accumulated + self._cost_cents_estimate > self._still_clip_cost_cents_max:
                raise StillCostCeilingError(
                    f"clip {script_id} accumulated still spend {accumulated}c + "
                    f"projected {self._cost_cents_estimate}c would exceed "
                    f"still_clip_cost_cents_max={self._still_clip_cost_cents_max}"
                )

        full_prompt = (
            f"{prompt}, {self._style_suffix}".strip(", ")
            if self._style_suffix
            else prompt
        )

        body = {
            "model": self.model,
            "prompt": full_prompt,
            "size": STILL_SIZE,
        }
        response = self._post_with_retry("/images", body)

        image_bytes = base64.b64decode(self._extract_image_b64(response))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(image_bytes)

        cost_cents = self._cost_cents_estimate
        usage = response.get("usage") or {}
        if usage.get("cost") is not None:
            # A sub-cent charge (Nano Banana 2 is ~0.4c) still floors to 1c
            # so it is never silently dropped from the per-Clip ledger.
            cost_cents = max(1, round(usage["cost"] * 100))

        if self._repo is not None and script_id is not None:
            self._repo.quota_record(
                "openrouter_still",
                cost_cents,
                provider="openrouter",
                script_id=script_id,
            )

        return StillResult(path=dest, cost_cents=cost_cents, raw=response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clip_still_spend(self, script_id: str) -> int:
        """Sum of openrouter_still spend already attributed to this Clip.

        Deliberately scoped to endpoint='openrouter_still' (not
        Repository.quota_script_total, which sums ALL openrouter spend
        including video) so INV-3's 20c still cap stays a separate bucket
        from the 150c per-Clip video cap. Repository is not extended with a
        new method here — this ticket's file scope excludes
        src/state/repository.py — so the query runs directly against the
        connection Repository already exposes as `.conn`.
        """
        if self._repo is None:
            return 0
        row = self._repo.conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage "
            "WHERE provider='openrouter' AND endpoint='openrouter_still' "
            "AND script_id=?",
            (script_id,),
        ).fetchone()
        return int(row["s"]) if row else 0

    @staticmethod
    def _extract_image_b64(response: dict) -> str:
        data = response.get("data") or []
        if not data or "b64_json" not in data[0]:
            raise ValueError(
                f"OpenRouter image response missing data[0].b64_json: {response}"
            )
        return data[0]["b64_json"]

    def _check_response(self, resp: requests.Response) -> None:
        """Issue 61 / INV-12 / INV-6: translate a 401/403 into a typed,
        key-free auth error before raise_for_status's generic HTTPError has
        a chance to surface. Mirrors
        OpenRouterKlingClient._check_response."""
        if resp.status_code in (401, 403):
            raise OpenRouterAuthError(
                f"OpenRouter authentication failed (HTTP {resp.status_code}); "
                "check OPENROUTER_API_KEY"
            )
        resp.raise_for_status()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _post_with_retry(self, path: str, body: dict) -> dict:
        resp = self._session.post(
            _BASE_URL + path,
            json=body,
            headers=self._headers(),
            timeout=30,
        )
        self._check_response(resp)
        return resp.json()
