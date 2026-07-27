"""OpenRouter Seedance 2.0 Fast image-to-video provider (ADR-0009).

API: https://openrouter.ai/api/v1/videos
Auth: Bearer {OPENROUTER_API_KEY}
Model: bytedance/seedance-2.0-fast — id and per-second billing rate are NOT
hardcoded here. Both are required constructor arguments so the caller must
source them from config (`AiGenConfig.seedance_model` /
`AiGenConfig.seedance_rate_cents_per_second`) — the cost projection INV-1/
INV-2 depend on must never be a magic number in code.

Workflow mirrors OpenRouterKlingClient (submit/poll/download), with two
differences driven by ADR-0009:
  - submit() supports first_frame_path (image-to-video conditioning) —
    Seedance's headline feature, encoded the same way Kling does (base64
    data-URI in body["image"]).
  - cost_cents is derived LOCALLY from the actual generated duration the
    provider reports times the configured per-second rate, rounded UP —
    it does not trust an OpenRouter-reported `usage.cost` field, so the
    ledger never under-reports spend on a partial/short render.

Wire schema assumption (DOCUMENTED, UNVERIFIED — OpenRouter does not
publish a Seedance-specific schema at time of writing): the submit/poll
response shape is assumed to mirror Kling's — {"id", "status",
"unsigned_urls", "duration", ...} — with the same status strings
(pending/in_progress/completed/failed). This assumption is locked by the
fixtures in tests/test_seedance_provider.py; if OpenRouter's real schema
differs, update _STATUS_MAP / _parse_response and the fixtures together.

Status mapping (OpenRouter → GenerationStatus):
  pending     → QUEUED
  in_progress → RUNNING
  completed   → SUCCEEDED
  failed      → FAILED
"""

from __future__ import annotations

import base64
import math
import os
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import GenerationStatus, Provider, ShotResult

_BASE_URL = "https://openrouter.ai/api/v1"

_STATUS_MAP: dict[str, GenerationStatus] = {
    "pending": GenerationStatus.QUEUED,
    "in_progress": GenerationStatus.RUNNING,
    "completed": GenerationStatus.SUCCEEDED,
    "failed": GenerationStatus.FAILED,
}


def _is_retryable(exc: BaseException) -> bool:
    """INV-12: 5xx / connection / timeout retry; 401/403 (and other 4xx)
    fail fast — exactly one attempt, no retry budget burned on a request
    that can never succeed."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and 500 <= status < 600
    return False


class OpenRouterSeedanceClient(Provider):
    provider_name = "seedance"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str,
        rate_cents_per_second: float,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self.model = model
        self.rate_cents_per_second = rate_cents_per_second
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def submit(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "9:16",
        first_frame_path: Path | None = None,
    ) -> str:
        """Submit a video job. Returns OpenRouter job id.

        When first_frame_path is None, submits text-to-video (no "image"
        key in the body). When given, the still conditions Seedance's
        image-to-video generation (ADR-0009).
        """
        body = {
            "model": self.model,
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
            "enable_audio": False,
        }
        if first_frame_path is not None:
            body["image"] = self._encode_first_frame(first_frame_path)
        response = self._post_with_retry("/videos", body)
        job_id = response.get("id")
        if not job_id:
            raise ValueError(f"OpenRouter submit: no id in response: {response}")
        return job_id

    def poll(self, external_id: str) -> ShotResult:
        """Query job status. Returns ShotResult with current state."""
        response = self._get_with_retry(f"/videos/{external_id}")
        return self._parse_response(external_id, response)

    def download(self, url: str, dest: Path) -> Path:
        """Stream download video to dest path. Returns dest."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers() if "openrouter.ai" in url else {}
        resp = self._session.get(url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_first_frame(path: Path) -> str:
        """Base64 data-URI encode a first-frame still for image-to-video
        conditioning."""
        data = path.read_bytes()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    def _parse_response(self, external_id: str, response: dict) -> ShotResult:
        raw_status = response.get("status", "pending")
        status = _STATUS_MAP.get(raw_status, GenerationStatus.QUEUED)

        download_url: str | None = None
        if status == GenerationStatus.SUCCEEDED:
            urls = response.get("unsigned_urls") or []
            if urls:
                download_url = urls[0]

        error: str | None = None
        if status == GenerationStatus.FAILED:
            error = response.get("error") or "unknown error"

        # cost_cents is derived from actual generated duration, never a
        # provider-reported usage.cost — rounded UP so the ledger never
        # under-reports spend (INV-1/INV-2).
        cost_cents: int | None = None
        if status == GenerationStatus.SUCCEEDED:
            duration = response.get("duration")
            if duration is not None:
                cost_cents = math.ceil(float(duration) * self.rate_cents_per_second)

        return ShotResult(
            external_id=external_id,
            status=status,
            download_url=download_url,
            cost_cents=cost_cents,
            error=error,
            raw=response,
        )

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
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get_with_retry(self, path: str) -> dict:
        resp = self._session.get(
            _BASE_URL + path,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
