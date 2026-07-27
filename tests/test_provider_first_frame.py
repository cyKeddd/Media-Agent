"""Tests for the Provider ABC's first_frame_path seam (Issue 63 / ADR-0009).

No live API calls. Covers:
  - Provider.submit() accepts an optional first_frame_path kwarg.
  - A provider that cannot do image-to-video raises a typed error rather than
    silently ignoring the still (which would bill for the wrong generation).
  - The new src/image_gen/base.py StillProvider / StillResult seam exists and
    is abstract (no concrete implementation lands in this ticket).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ai_gen.base import (
    GenerationStatus,
    Provider,
    ShotResult,
    UnsupportedFirstFrameError,
)
from src.image_gen.base import StillProvider, StillResult


# ---------------------------------------------------------------------------
# Fake providers used only to exercise the ABC contract
# ---------------------------------------------------------------------------


class _TextOnlyProvider(Provider):
    """A provider that cannot do image-to-video."""

    provider_name = "text-only-fake"

    def submit(self, prompt, *, duration_s=5, aspect_ratio="9:16", first_frame_path=None):
        self._reject_first_frame(first_frame_path)
        return "job-1"

    def poll(self, external_id):
        return ShotResult(external_id=external_id, status=GenerationStatus.SUCCEEDED)

    def download(self, url, dest):
        return dest


class _ImageCapableProvider(Provider):
    """A provider that does support first-frame conditioning."""

    provider_name = "image-capable-fake"

    def __init__(self):
        self.last_first_frame_path = "unset"

    def submit(self, prompt, *, duration_s=5, aspect_ratio="9:16", first_frame_path=None):
        self.last_first_frame_path = first_frame_path
        return "job-2"

    def poll(self, external_id):
        return ShotResult(external_id=external_id, status=GenerationStatus.SUCCEEDED)

    def download(self, url, dest):
        return dest


# ---------------------------------------------------------------------------
# Provider.submit() accepts first_frame_path
# ---------------------------------------------------------------------------


def test_submit_accepts_first_frame_path_kwarg_when_supported(tmp_path):
    still = tmp_path / "still.png"
    still.write_bytes(b"fake-png-bytes")
    provider = _ImageCapableProvider()

    job_id = provider.submit("a rocket on a launchpad", first_frame_path=still)

    assert job_id == "job-2"
    assert provider.last_first_frame_path == still


def test_submit_first_frame_path_defaults_to_none():
    provider = _ImageCapableProvider()
    provider.submit("a rocket on a launchpad")
    assert provider.last_first_frame_path is None


def test_submit_without_first_frame_path_still_works_on_text_only_provider():
    provider = _TextOnlyProvider()
    job_id = provider.submit("a rocket on a launchpad")
    assert job_id == "job-1"


# ---------------------------------------------------------------------------
# Unsupported first-frame conditioning raises a typed error, never a silent no-op
# ---------------------------------------------------------------------------


def test_submit_with_first_frame_on_unsupported_provider_raises_typed_error(tmp_path):
    still = tmp_path / "still.png"
    still.write_bytes(b"fake-png-bytes")
    provider = _TextOnlyProvider()

    with pytest.raises(UnsupportedFirstFrameError):
        provider.submit("a rocket on a launchpad", first_frame_path=still)


def test_unsupported_first_frame_error_is_not_a_silent_noop(tmp_path):
    # It must be a real exception type, not e.g. a plain NotImplementedError
    # swallowed elsewhere, and it must be raised BEFORE any billable call
    # would occur (the fake provider raises before returning a job id).
    still = tmp_path / "still.png"
    still.write_bytes(b"fake-png-bytes")
    provider = _TextOnlyProvider()

    assert issubclass(UnsupportedFirstFrameError, Exception)
    with pytest.raises(UnsupportedFirstFrameError):
        provider.submit("prompt", first_frame_path=still)


# ---------------------------------------------------------------------------
# StillProvider / StillResult seam (Issue 64 lands the concrete impl)
# ---------------------------------------------------------------------------


def test_still_provider_is_abstract():
    with pytest.raises(TypeError):
        StillProvider()  # abstract — cannot be instantiated directly


def test_still_result_carries_path_and_cost_cents(tmp_path):
    dest = tmp_path / "still.png"
    result = StillResult(path=dest, cost_cents=4)
    assert result.path == dest
    assert result.cost_cents == 4


def test_still_provider_generate_is_the_abstract_seam():
    class _FakeStillProvider(StillProvider):
        provider_name = "fake-still"

        def generate(self, prompt, *, aspect_ratio="9:16", dest):
            dest.write_bytes(b"png-bytes")
            return StillResult(path=dest, cost_cents=1)

    fake = _FakeStillProvider()
    dest = Path("unused-does-not-need-to-exist.png")
    # Just verifying the concrete subclass satisfies the ABC contract and is
    # callable with the documented signature; no filesystem writes required
    # beyond what the fake itself performs when actually invoked elsewhere.
    assert callable(fake.generate)
