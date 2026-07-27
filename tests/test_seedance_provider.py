"""Unit tests for OpenRouterSeedanceClient — no live API calls.

Covers Issue 65 (Seedance 2.0 Fast image-to-video provider, ADR-0009):
  - Provider ABC conformance (submit/poll/download + first_frame_path)
  - Config-sourced model id + per-second rate (no magic numbers)
  - cost_cents rounded UP from actual generated duration
  - INV-12 retry policy: 401 fails fast (exactly one attempt), 503 retries x3
  - wait_for_completion surfaces TimeoutError, not a hang
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.ai_gen.base import GenerationStatus, Provider, ShotResult
from src.ai_gen.openrouter_seedance import OpenRouterSeedanceClient, _STATUS_MAP

_MODEL = "bytedance/seedance-2.0-fast"
_RATE_CENTS_PER_SECOND = 5.38  # $0.0538/s — matches config.yaml ai_gen.seedance_rate_cents_per_second


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return OpenRouterSeedanceClient(
        api_key="sk-or-test-key",
        model=_MODEL,
        rate_cents_per_second=_RATE_CENTS_PER_SECOND,
    )


def _mock_response(body: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status = MagicMock()
    return r


def _http_error_response(status_code: int) -> MagicMock:
    """A response whose raise_for_status() raises an HTTPError carrying
    that status code, the way `requests` really behaves."""
    err_resp = MagicMock()
    err_resp.status_code = status_code
    error = requests.HTTPError(f"{status_code} error")
    error.response = err_resp
    r = MagicMock()
    r.raise_for_status.side_effect = error
    return r


# ---------------------------------------------------------------------------
# Provider ABC conformance
# ---------------------------------------------------------------------------


def test_seedance_client_is_a_provider(client):
    assert isinstance(client, Provider)


def test_provider_name_is_seedance(client):
    assert client.provider_name == "seedance"


# ---------------------------------------------------------------------------
# Config-sourced model / rate — no magic numbers in code
# ---------------------------------------------------------------------------


def test_model_comes_from_constructor_arg_not_hardcoded():
    c = OpenRouterSeedanceClient(api_key="k", model="some/other-model", rate_cents_per_second=1.0)
    assert c.model == "some/other-model"


def test_rate_comes_from_constructor_arg_not_hardcoded():
    c = OpenRouterSeedanceClient(api_key="k", model=_MODEL, rate_cents_per_second=9.99)
    assert c.rate_cents_per_second == 9.99


def test_model_and_rate_are_required_kwargs():
    with pytest.raises(TypeError):
        OpenRouterSeedanceClient(api_key="k")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# submit() — text-to-video (no first frame)
# ---------------------------------------------------------------------------


def test_submit_returns_job_id(client):
    mock_resp = _mock_response({"id": "gen-sd-1", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp):
        job_id = client.submit("a product reveal on a clean studio backdrop")
    assert job_id == "gen-sd-1"


def test_submit_posts_to_correct_url(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    url = mock_post.call_args[0][0]
    assert url == "https://openrouter.ai/api/v1/videos"


def test_submit_sends_configured_model(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    body = mock_post.call_args[1]["json"]
    assert body["model"] == _MODEL


def test_submit_without_first_frame_is_text_to_video_only(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("weird biology fact", duration_s=4, aspect_ratio="9:16")
    body = mock_post.call_args[1]["json"]
    assert body == {
        "model": _MODEL,
        "prompt": "weird biology fact",
        "duration": 4,
        "aspect_ratio": "9:16",
        "enable_audio": False,
    }
    assert "image" not in body


def test_submit_uses_bearer_auth(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer sk-or-test-key"


def test_submit_raises_if_no_id(client):
    mock_resp = _mock_response({"status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(ValueError, match="no id"):
            client.submit("prompt")


# ---------------------------------------------------------------------------
# submit() — first_frame_path (image-to-video, ADR-0009)
# ---------------------------------------------------------------------------


def test_submit_with_first_frame_includes_image_in_payload(tmp_path, client):
    still = tmp_path / "still.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt", first_frame_path=still)
    body = mock_post.call_args[1]["json"]
    assert body["image"].startswith("data:image/png;base64,")


def test_submit_with_first_frame_jpeg_uses_jpeg_mime(tmp_path, client):
    still = tmp_path / "still.jpg"
    still.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt", first_frame_path=still)
    body = mock_post.call_args[1]["json"]
    assert body["image"].startswith("data:image/jpeg;base64,")


def test_submit_with_explicit_none_first_frame_matches_default(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt", first_frame_path=None)
    body = mock_post.call_args[1]["json"]
    assert "image" not in body


# ---------------------------------------------------------------------------
# poll() + cost_cents (INV-1 / INV-2)
# ---------------------------------------------------------------------------


def test_poll_completed_extracts_download_url(client):
    mock_resp = _mock_response({
        "id": "gen-sd",
        "status": "completed",
        "unsigned_urls": ["https://cdn.openrouter.ai/videos/gen-sd.mp4"],
        "duration": 4,
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-sd")
    assert result.status == GenerationStatus.SUCCEEDED
    assert result.download_url == "https://cdn.openrouter.ai/videos/gen-sd.mp4"


def test_cost_cents_for_4s_shot_is_22_rounded_up(client):
    """Acceptance criterion, asserted exactly: 4s * $0.0538/s = 21.52c -> 22c."""
    mock_resp = _mock_response({
        "id": "gen-sd",
        "status": "completed",
        "unsigned_urls": ["https://cdn.openrouter.ai/videos/gen-sd.mp4"],
        "duration": 4,
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-sd")
    assert result.cost_cents == 22


def test_cost_cents_rounds_up_not_down(client):
    """3s * $0.0538/s = 16.14c -> must round up to 17, never truncate to 16."""
    mock_resp = _mock_response({
        "id": "gen-sd",
        "status": "completed",
        "unsigned_urls": ["https://cdn.openrouter.ai/videos/gen-sd.mp4"],
        "duration": 3,
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-sd")
    assert result.cost_cents == 17


def test_cost_cents_none_when_not_succeeded(client):
    mock_resp = _mock_response({"id": "gen-sd", "status": "pending"})
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-sd")
    assert result.cost_cents is None


def test_poll_failed_captures_error(client):
    mock_resp = _mock_response({
        "id": "gen-sd",
        "status": "failed",
        "error": "content policy violation",
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-sd")
    assert result.status == GenerationStatus.FAILED
    assert "content policy" in result.error


def test_status_map_covers_all_known_statuses():
    assert set(_STATUS_MAP) == {"pending", "in_progress", "completed", "failed"}


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


def test_download_writes_bytes_to_dest(tmp_path, client):
    fake_bytes = b"fake_mp4_bytes_from_seedance"
    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [fake_bytes]
    mock_resp.raise_for_status = MagicMock()
    with patch.object(client._session, "get", return_value=mock_resp):
        dest = client.download("https://cdn.openrouter.ai/v.mp4", tmp_path / "shot.mp4")
    assert dest.read_bytes() == fake_bytes


# ---------------------------------------------------------------------------
# INV-12 retry policy
# ---------------------------------------------------------------------------


def test_submit_401_makes_exactly_one_attempt(client):
    mock_resp = _http_error_response(401)
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(requests.HTTPError):
            client.submit("prompt")
    assert mock_post.call_count == 1


def test_submit_403_makes_exactly_one_attempt(client):
    mock_resp = _http_error_response(403)
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(requests.HTTPError):
            client.submit("prompt")
    assert mock_post.call_count == 1


def test_submit_503_retries_three_times_then_succeeds(client):
    bad_resp = _http_error_response(503)
    good_resp = _mock_response({"id": "gen-recovered", "status": "pending"})
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        return bad_resp if call_count < 3 else good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", side_effect=side_effect):
        job_id = client.submit("prompt")

    assert job_id == "gen-recovered"
    assert call_count == 3


def test_submit_503_exhausts_at_three_attempts_and_raises(client):
    bad_resp = _http_error_response(503)
    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", return_value=bad_resp) as mock_post:
        with pytest.raises(requests.HTTPError):
            client.submit("prompt")
    assert mock_post.call_count == 3


def test_submit_retries_on_connection_error(client):
    good_resp = _mock_response({"id": "gen-xyz", "status": "pending"})
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise requests.ConnectionError("network down")
        return good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", side_effect=side_effect):
        job_id = client.submit("p")

    assert job_id == "gen-xyz"
    assert call_count == 2


# ---------------------------------------------------------------------------
# wait_for_completion() — must surface TimeoutError, never hang
# ---------------------------------------------------------------------------


def test_wait_for_completion_raises_timeout_error_not_hang(client):
    """A provider that never reaches a terminal status (stubbed 'timeout')
    must cause wait_for_completion to raise TimeoutError once its own
    deadline elapses — not hang, and not leak the underlying HTTP
    exception type."""
    mock_resp = _mock_response({"id": "gen-stuck", "status": "pending"})
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(TimeoutError):
            client.wait_for_completion("gen-stuck", poll_interval_s=0.01, timeout_s=0.05)


# ---------------------------------------------------------------------------
# Kling regression guard — Seedance must not have removed Kling
# ---------------------------------------------------------------------------


def test_kling_provider_still_importable_and_selectable():
    from src.ai_gen.openrouter_kling import OpenRouterKlingClient

    kling = OpenRouterKlingClient(api_key="k")
    assert isinstance(kling, Provider)
    assert kling.model == "kwaivgi/kling-v3.0-std"
