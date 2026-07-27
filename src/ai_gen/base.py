"""Provider ABC for AI video generators (Kling, Pika, MiniMax, …).

Each concrete provider implements submit/poll/download. The runner calls
these three methods; all provider-specific auth, retry, and response
parsing stays inside the concrete class.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class UnsupportedFirstFrameError(NotImplementedError):
    """Raised by Provider.submit() when called with first_frame_path on a
    provider that cannot do image-to-video conditioning.

    A provider must never silently drop the still and fall back to
    unconditioned text-to-video — that bills for the wrong generation
    without telling the caller. Raise this instead.
    """


class GenerationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class ShotResult:
    external_id: str
    status: GenerationStatus
    download_url: str | None = None
    cost_cents: int | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)


class Provider(ABC):
    """Abstract base for a text-to-video generator."""

    # Subclasses set this; runner uses it for logging and DB records.
    provider_name: str = "unknown"

    @abstractmethod
    def submit(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "9:16",
        first_frame_path: Path | None = None,
    ) -> str:
        """Submit a generation job. Returns provider-side external_id.

        first_frame_path (ADR-0009): an optional still to condition an
        image-to-video generation. Providers that cannot do image-to-video
        MUST raise UnsupportedFirstFrameError when it is not None — never
        silently ignore it and fall back to text-to-video.
        """

    def _reject_first_frame(self, first_frame_path: Path | None) -> None:
        """Helper for subclasses that do not support image-to-video.

        Call this at the top of submit() so an unsupported first_frame_path
        raises before any billable request is made.
        """
        if first_frame_path is not None:
            raise UnsupportedFirstFrameError(
                f"{self.provider_name}: does not support first_frame_path "
                "(image-to-video conditioning)"
            )

    @abstractmethod
    def poll(self, external_id: str) -> ShotResult:
        """Check the current status of a job."""

    @abstractmethod
    def download(self, url: str, dest: Path) -> Path:
        """Download the generated video to dest. Returns dest path."""

    def wait_for_completion(
        self,
        external_id: str,
        *,
        poll_interval_s: int = 15,
        timeout_s: int = 600,
    ) -> ShotResult:
        """Poll until succeeded/failed or timeout. Raises TimeoutError."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self.poll(external_id)
            if result.status in (GenerationStatus.SUCCEEDED, GenerationStatus.FAILED):
                return result
            time.sleep(poll_interval_s)
        raise TimeoutError(
            f"{self.provider_name}: job {external_id} did not finish within {timeout_s}s"
        )
