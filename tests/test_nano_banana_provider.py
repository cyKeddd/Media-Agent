"""Issue 64 — NanoBananaProvider (google/gemini-3.1-flash-image still generator).

No live API calls: every test drives a fake HTTP layer via
unittest.mock.patch.object(provider._session, "post", ...).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.ai_gen.base import OpenRouterAuthError
from src.image_fetch.errors import LivingPersonEntityError
from src.image_gen.base import StillResult
from src.image_gen.nano_banana import NanoBananaProvider, StillCostCeilingError
from src.state import Repository, connect, initialize_schema


def _repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _mock_response(body: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


_FAKE_B64 = "ZmFrZS1wbmctYnl0ZXM="  # base64("fake-png-bytes")


def _ok_body(cost: float = 0.004) -> dict:
    return {"data": [{"b64_json": _FAKE_B64}], "usage": {"cost": cost}}


@pytest.fixture
def provider():
    return NanoBananaProvider(api_key="sk-or-test-key")


# ---------------------------------------------------------------------------
# Default model read from config, not hardcoded
# ---------------------------------------------------------------------------


def test_default_model_is_nano_banana():
    p = NanoBananaProvider(api_key="k")
    assert p.model == "google/gemini-3.1-flash-image"


def test_custom_model_from_config_is_honoured():
    p = NanoBananaProvider(api_key="k", model="some/other-model")
    assert p.model == "some/other-model"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a neutral product shot", dest=_dest())
    body = mock_post.call_args[1]["json"]
    assert body["model"] == "some/other-model"


def _dest(tmp_path=None):
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp(prefix="nano_banana_test_"))
    return d / "still.png"


# ---------------------------------------------------------------------------
# generate() — happy path
# ---------------------------------------------------------------------------


def test_generate_writes_image_bytes_to_dest(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(provider._session, "post", return_value=mock_resp):
        result = provider.generate("a neutral product shot", dest=dest)
    assert dest.exists()
    assert dest.read_bytes() == b"fake-png-bytes"
    assert isinstance(result, StillResult)
    assert result.path == dest


def test_generate_returns_populated_cost_cents(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body(cost=0.004))
    with patch.object(provider._session, "post", return_value=mock_resp):
        result = provider.generate("a neutral product shot", dest=dest)
    assert result.cost_cents is not None
    assert result.cost_cents >= 1


def test_generate_requests_size_at_least_1080_short_edge_9x16(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(provider._session, "post", return_value=mock_resp) as mock_post:
        provider.generate("a neutral product shot", dest=dest)
    body = mock_post.call_args[1]["json"]
    width, height = (int(x) for x in body["size"].split("x"))
    assert min(width, height) >= 1080
    assert (width, height) == (1080, 1920)  # 9:16


def test_generate_posts_to_images_endpoint(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(provider._session, "post", return_value=mock_resp) as mock_post:
        provider.generate("a neutral product shot", dest=dest)
    url = mock_post.call_args[0][0]
    assert url == "https://openrouter.ai/api/v1/images"


def test_generate_uses_bearer_auth(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(provider._session, "post", return_value=mock_resp) as mock_post:
        provider.generate("a neutral product shot", dest=dest)
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer sk-or-test-key"


def test_generate_creates_parent_dirs(tmp_path, provider):
    dest = tmp_path / "a" / "b" / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(provider._session, "post", return_value=mock_resp):
        provider.generate("a neutral product shot", dest=dest)
    assert dest.exists()


# ---------------------------------------------------------------------------
# Style suffix reuse (ADR-0009) — same field + concatenation pattern as
# gen_run._generate_clip applies to ai_video shots (ai_gen.style_suffix).
# ---------------------------------------------------------------------------


def test_style_suffix_is_appended_to_prompt(tmp_path):
    p = NanoBananaProvider(api_key="k", style_suffix="premium tech magazine look")
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a folding phone", dest=dest)
    body = mock_post.call_args[1]["json"]
    assert body["prompt"] == "a folding phone, premium tech magazine look"


def test_empty_style_suffix_leaves_prompt_untouched(tmp_path):
    p = NanoBananaProvider(api_key="k", style_suffix="")
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a folding phone", dest=dest)
    body = mock_post.call_args[1]["json"]
    assert body["prompt"] == "a folding phone"


# ---------------------------------------------------------------------------
# INV-8 — no living individuals, reusing the real_image gate.
# ---------------------------------------------------------------------------


def test_prompt_naming_living_person_rejected_before_any_http_call(tmp_path):
    p = NanoBananaProvider(
        api_key="k", living_person_patterns=["portrait of", "photo of", "headshot"],
    )
    dest = tmp_path / "still.png"
    with patch.object(p._session, "post") as mock_post:
        with pytest.raises(LivingPersonEntityError):
            p.generate("a photo of Tim Cook holding an iPhone", dest=dest)
    mock_post.assert_not_called()


def test_prompt_without_living_person_pattern_proceeds(tmp_path):
    p = NanoBananaProvider(
        api_key="k", living_person_patterns=["portrait of", "photo of", "headshot"],
    )
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a folding phone on a table", dest=dest)
    mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# INV-3 — per-still and per-clip cost ceilings.
# ---------------------------------------------------------------------------


def test_still_projected_above_5c_is_refused_before_http_call(tmp_path):
    p = NanoBananaProvider(
        api_key="k", still_cost_cents_max=5, cost_cents_estimate=6,
    )
    dest = tmp_path / "still.png"
    with patch.object(p._session, "post") as mock_post:
        with pytest.raises(StillCostCeilingError, match="still_cost_cents_max"):
            p.generate("a folding phone", dest=dest)
    mock_post.assert_not_called()


def test_still_at_or_under_5c_proceeds(tmp_path):
    p = NanoBananaProvider(
        api_key="k", still_cost_cents_max=5, cost_cents_estimate=5,
    )
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a folding phone", dest=dest)
    mock_post.assert_called_once()


def test_clip_already_at_20c_of_stills_refuses_next(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter_still", 20, provider="openrouter", script_id="clip-1")

    p = NanoBananaProvider(
        api_key="k",
        still_clip_cost_cents_max=20,
        cost_cents_estimate=1,
        repo=repo,
    )
    dest = tmp_path / "still.png"
    with patch.object(p._session, "post") as mock_post:
        with pytest.raises(StillCostCeilingError, match="still_clip_cost_cents_max"):
            p.generate("a folding phone", dest=dest, script_id="clip-1")
    mock_post.assert_not_called()


def test_clip_under_20c_of_stills_proceeds_and_accumulates(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter_still", 10, provider="openrouter", script_id="clip-1")

    p = NanoBananaProvider(
        api_key="k",
        still_clip_cost_cents_max=20,
        cost_cents_estimate=1,
        repo=repo,
    )
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body(cost=0.004))
    with patch.object(p._session, "post", return_value=mock_resp):
        p.generate("a folding phone", dest=dest, script_id="clip-1")
    # 10 (seed) + 1 (this still, cost floors to 1c minimum) == 11
    assert repo.quota_script_total("clip-1") == 11


def test_still_spend_isolated_from_video_spend_on_same_clip(tmp_path):
    """A Clip already at its 150c video cap must not block a cheap still —
    INV-3's 20c ceiling is a separate bucket, keyed on endpoint='openrouter_still'."""
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 150, provider="openrouter", script_id="clip-1")

    p = NanoBananaProvider(
        api_key="k",
        still_clip_cost_cents_max=20,
        cost_cents_estimate=1,
        repo=repo,
    )
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp) as mock_post:
        p.generate("a folding phone", dest=dest, script_id="clip-1")
    mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# INV-2 — quota metered with provider='openrouter' and script_id.
# ---------------------------------------------------------------------------


def test_cost_recorded_with_provider_openrouter_and_script_id(tmp_path):
    repo = _repo(tmp_path)
    p = NanoBananaProvider(api_key="k", repo=repo)
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body(cost=0.004))
    with patch.object(p._session, "post", return_value=mock_resp):
        p.generate("a folding phone", dest=dest, script_id="clip-9")
    row = repo.conn.execute(
        "SELECT provider, script_id, units, endpoint FROM quota_usage"
    ).fetchone()
    assert row["provider"] == "openrouter"
    assert row["script_id"] == "clip-9"
    assert row["units"] >= 1


def test_no_quota_write_without_script_id(tmp_path):
    repo = _repo(tmp_path)
    p = NanoBananaProvider(api_key="k", repo=repo)
    dest = tmp_path / "still.png"
    mock_resp = _mock_response(_ok_body())
    with patch.object(p._session, "post", return_value=mock_resp):
        p.generate("a folding phone", dest=dest)
    row = repo.conn.execute("SELECT COUNT(*) AS n FROM quota_usage").fetchone()
    assert row["n"] == 0


# ---------------------------------------------------------------------------
# INV-12 — retry policy: 5xx/timeout retry x3, 401/403 exactly once.
# ---------------------------------------------------------------------------


def test_retries_on_503_then_succeeds(tmp_path, provider):
    dest = tmp_path / "still.png"
    good = _mock_response(_ok_body())
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            resp = MagicMock(status_code=503)
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
            return resp
        return good

    with patch("tenacity.nap.time.sleep"), \
         patch.object(provider._session, "post", side_effect=side_effect):
        provider.generate("a folding phone", dest=dest)
    assert call_count == 2


def test_retries_on_connection_error(tmp_path, provider):
    dest = tmp_path / "still.png"
    good = _mock_response(_ok_body())
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise requests.ConnectionError("network down")
        return good

    with patch("tenacity.nap.time.sleep"), \
         patch.object(provider._session, "post", side_effect=side_effect):
        provider.generate("a folding phone", dest=dest)
    assert call_count == 2


def test_gives_up_after_3_attempts_on_persistent_503(tmp_path, provider):
    dest = tmp_path / "still.png"

    def side_effect(*a, **kw):
        resp = MagicMock(status_code=503)
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(provider._session, "post", side_effect=side_effect) as mock_post:
        with pytest.raises(requests.HTTPError):
            provider.generate("a folding phone", dest=dest)
    assert mock_post.call_count == 3


def test_401_raises_openrouter_auth_error_after_exactly_one_attempt(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response({}, status_code=401)
    with patch.object(provider._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(OpenRouterAuthError):
            provider.generate("a folding phone", dest=dest)
    assert mock_post.call_count == 1


def test_403_raises_openrouter_auth_error_after_exactly_one_attempt(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response({}, status_code=403)
    with patch.object(provider._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(OpenRouterAuthError):
            provider.generate("a folding phone", dest=dest)
    assert mock_post.call_count == 1


def test_auth_error_message_never_contains_key(tmp_path, provider):
    dest = tmp_path / "still.png"
    mock_resp = _mock_response({}, status_code=401)
    with patch.object(provider._session, "post", return_value=mock_resp):
        with pytest.raises(OpenRouterAuthError) as excinfo:
            provider.generate("a folding phone", dest=dest)
    assert "sk-or-test-key" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# INV-10 — implements StillProvider ABC, swappable by config.
# ---------------------------------------------------------------------------


def test_provider_name_is_nano_banana():
    p = NanoBananaProvider(api_key="k")
    assert p.provider_name == "nano_banana"


def test_is_instance_of_still_provider():
    from src.image_gen.base import StillProvider

    p = NanoBananaProvider(api_key="k")
    assert isinstance(p, StillProvider)
