"""StillProvider ABC for AI still-image generators (Nano Banana 2, …).

ADR-0009: every Shot is generated image-first (a Generated still), then
animated by a video Provider (src/ai_gen/base.py) via first_frame_path. This
module only establishes the seam — the concrete implementation lands in
Issue 64.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StillResult:
    path: Path
    cost_cents: int | None = None
    raw: dict = field(default_factory=dict)


class StillProvider(ABC):
    """Abstract base for a text-to-still generator producing a Provider
    first frame."""

    # Subclasses set this; callers use it for logging and DB records.
    provider_name: str = "unknown"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        dest: Path,
    ) -> StillResult:
        """Generate a still image at dest. Returns StillResult with the
        written path and cost."""
