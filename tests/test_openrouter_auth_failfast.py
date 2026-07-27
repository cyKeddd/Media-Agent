"""Issue 61 — fail-fast on OpenRouter auth errors (INV-12 / INV-6).

Covers OpenRouterKlingClient (src/ai_gen/openrouter_kling.py):
  - a stubbed 401 aborts immediately: raises OpenRouterAuthError, exactly
    one HTTP attempt (no retry loop burned on a request that can never
    succeed)
  - a stubbed 403 behaves identically to 401
  - a stubbed 503 still retries x3 per the existing transient-failure
    policy (regression guard)
  - the auth error message never contains the API key value (INV-6)
  - both submit() (POST) and poll() (GET) apply the same policy

No live OpenRouter calls — the session's post/get is patched with a fake
HTTP layer (MagicMock responses), matching the existing pattern in
tests/ai_gen/test_openrouter_kling.py and tests/test_seedance_provider.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai_gen.base import OpenRouterAuthError
from src.ai_gen.openrouter_kling import OpenRouterKlingClient

_SECRET_KEY = "sk-or-v1-super-secret-do-not-leak-0123456789abcdef"


@pytest.fixture
def client():
    return OpenRouterKlingClient(api_key=_SECRET_KEY)


def _mock_response(body: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status = MagicMock()
    r.status_code = 200
    return r


def _status_response(status_code: int) -> MagicMock:
    """A response whose status_code is set the way `requests` really sets
    it; raise_for_status() only raises for codes >= 400 (real behaviour),
    so 401/403 must be caught by _check_response's explicit status check,
    not by relying on raise_for_status."""
    r = MagicMock()
    r.status_code = status_code
    if status_code >= 400:
        import requests

        err_resp = MagicMock()
        err_resp.status_code = status_code
        error = requests.HTTPError(f"{status_code} error")
        error.response = err_resp
        r.raise_for_status.side_effect = error
    else:
        r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# submit() (POST) — 401 / 403 fail fast
# ---------------------------------------------------------------------------


def test_submit_401_raises_auth_error(client):
    mock_resp = _status_response(401)
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(OpenRouterAuthError):
            client.submit("prompt")


def test_submit_401_makes_exactly_one_attempt(client):
    mock_resp = _status_response(401)
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(OpenRouterAuthError):
            client.submit("prompt")
    assert mock_post.call_count == 1


def test_submit_403_raises_auth_error(client):
    mock_resp = _status_response(403)
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(OpenRouterAuthError):
            client.submit("prompt")


def test_submit_403_makes_exactly_one_attempt(client):
    mock_resp = _status_response(403)
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(OpenRouterAuthError):
            client.submit("prompt")
    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# poll() (GET) — same policy applies
# ---------------------------------------------------------------------------


def test_poll_401_raises_auth_error_with_exactly_one_attempt(client):
    mock_resp = _status_response(401)
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        with pytest.raises(OpenRouterAuthError):
            client.poll("gen-1")
    assert mock_get.call_count == 1


def test_poll_403_raises_auth_error_with_exactly_one_attempt(client):
    mock_resp = _status_response(403)
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        with pytest.raises(OpenRouterAuthError):
            client.poll("gen-1")
    assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# INV-6 — the auth error message never contains the key
# ---------------------------------------------------------------------------


def test_auth_error_message_never_contains_the_key(client):
    mock_resp = _status_response(401)
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(OpenRouterAuthError) as exc_info:
            client.submit("prompt")
    assert _SECRET_KEY not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Regression guard — 503 still retries x3 per the existing transient policy
# ---------------------------------------------------------------------------


def test_submit_503_retries_three_times_then_succeeds(client):
    bad_resp = _status_response(503)
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
    bad_resp = _status_response(503)
    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", return_value=bad_resp) as mock_post:
        import requests

        with pytest.raises(requests.HTTPError):
            client.submit("prompt")
    assert mock_post.call_count == 3


def test_poll_503_retries_three_times_then_succeeds(client):
    bad_resp = _status_response(503)
    good_resp = _mock_response({"id": "gen-1", "status": "pending"})
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        return bad_resp if call_count < 3 else good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "get", side_effect=side_effect):
        result = client.poll("gen-1")

    assert result.external_id == "gen-1"
    assert call_count == 3


def test_submit_still_retries_on_connection_error(client):
    """Broader regression guard: the switch from retry_if_exception_type
    to the OpenRouterKlingClient._is_retryable predicate must not drop the
    pre-existing connection-error retry behaviour."""
    import requests

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
# Other 4xx (not 401/403) still fail fast, but as plain HTTPError — not
# mistaken for an auth failure.
# ---------------------------------------------------------------------------


def test_submit_400_is_not_an_auth_error(client):
    import requests

    mock_resp = _status_response(400)
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        with pytest.raises(requests.HTTPError):
            client.submit("prompt")
    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Run-level abort (INV-12) — added by the parent agent after review.
#
# The provider-level tests above prove the typed error is raised with exactly
# one attempt. They do NOT prove the *run* aborts or that an `auth_failed`
# alert is ever appended, which is what the ticket's acceptance criteria and
# INV-12 actually require. Before this test, nothing in src/ caught
# OpenRouterAuthError and the string "auth_failed" appeared only in a
# docstring — the alert could never fire in production.
#
# Scaffolding is reused from tests/test_weekly_spend_ceiling.py rather than
# duplicated, so both run-level gates share one stub definition.
# ---------------------------------------------------------------------------

import pytest

from tests.test_weekly_spend_ceiling import (
    _GenStubConfig,
    _ai_video_script,
    _repo,
)
from src.policy_gate.evaluator import PolicyVerdict
from pathlib import Path


def test_openrouter_401_aborts_the_whole_run_and_alerts(tmp_path):
    """A 401 mid-render aborts the run, appends `auth_failed`, and finalizes
    the run success=0 — distinct from the spend cap, which finishes success=1."""
    from src.ai_gen.base import OpenRouterAuthError
    from src.gen_run import run_generation

    repo = _repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)
    fake_scripts = [_ai_video_script("s1")]

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run.OpenRouterKlingClient"), \
         patch("src.gen_run.generate_shots",
               side_effect=OpenRouterAuthError("OpenRouter rejected the API key (401)")), \
         patch("src.gen_run.synthesize") as p_synth:
        with pytest.raises(OpenRouterAuthError):
            run_generation(
                repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
            )

    # Aborted before doing any further work on this or any later script.
    p_synth.assert_not_called()

    alerts = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "auth_failed" in alerts
    # INV-6: the alert must never carry key material.
    assert "sk-test" not in alerts

    row = repo.conn.execute(
        "SELECT success FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["success"] == 0
