"""Issue 67 — switch runtime defaults to image-first + Seedance (ADR-0009).

Verification-command for MED-13 / Issue 67. Covers:
  - config.yaml selects Seedance for video + Nano Banana 2 for stills, with
    every INV-1/INV-2/INV-3 ceiling present.
  - Cadence config expresses 5 Clips/week (D2).
  - INV-10 proof: build_video_provider() is a pure function of config —
    flipping ai_gen.model alone changes the constructed provider class.
  - The pre-billing cost projection is derived from the CONFIGURED
    provider's rate, not a Kling-shaped module constant (problem 3).
  - bootstrap --check fails clearly when a configured model id is
    unreachable, and is offline-safe (no live network call).
  - CONTEXT.md defines the two new ADR-0009 glossary terms.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ai_gen.factory import build_video_provider, estimate_shot_cost_cents
from src.ai_gen.openrouter_kling import OpenRouterKlingClient
from src.ai_gen.openrouter_seedance import OpenRouterSeedanceClient
from src.config_loader import load_config

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# config.yaml selects Seedance + Nano Banana 2, with INV ceilings present
# ---------------------------------------------------------------------------


def test_config_yaml_selects_seedance_for_video():
    cfg = load_config(str(ROOT / "config.yaml"))
    assert cfg.ai_gen.model == "bytedance/seedance-2.0-fast"


def test_config_yaml_selects_nano_banana_for_stills():
    cfg = load_config(str(ROOT / "config.yaml"))
    assert cfg.ai_gen.still_model == "google/gemini-3.1-flash-image"
    assert cfg.ai_gen.still_generation_enabled is True


def test_config_yaml_carries_all_inv3_ceilings():
    cfg = load_config(str(ROOT / "config.yaml"))
    assert cfg.ai_gen.weekly_spend_cents_ceiling == 800          # INV-1
    assert cfg.ai_gen.per_clip_cost_cents_max > 0                # INV-2
    assert cfg.ai_gen.still_cost_cents_max == 5                  # INV-3
    assert cfg.ai_gen.still_clip_cost_cents_max == 20            # INV-3


def test_config_yaml_retains_kling_as_commented_alternative():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "# model: \"kwaivgi/kling-v3.0-std\"" in text


# ---------------------------------------------------------------------------
# Cadence expresses 5 Clips/week (D2)
# ---------------------------------------------------------------------------


def test_cadence_expresses_five_clips_per_week():
    cfg = load_config(str(ROOT / "config.yaml"))
    assert cfg.clips_per_day * len(cfg.upload_weekdays) == 5


# ---------------------------------------------------------------------------
# INV-10 — provider built purely from config
# ---------------------------------------------------------------------------


class _AiGenCfg:
    def __init__(self, model: str):
        self.model = model
        self.seedance_rate_cents_per_second = 5.38


def test_build_video_provider_from_config_yields_seedance():
    ai_cfg = _AiGenCfg("bytedance/seedance-2.0-fast")
    provider = build_video_provider(ai_cfg, api_key="sk-or-v1-test")
    assert isinstance(provider, OpenRouterSeedanceClient)


def test_overriding_config_value_alone_yields_kling():
    """INV-10: the SAME construction call, only ai_cfg.model changed,
    yields a different concrete Provider class."""
    ai_cfg = _AiGenCfg("kwaivgi/kling-v3.0-std")
    provider = build_video_provider(ai_cfg, api_key="sk-or-v1-test")
    assert isinstance(provider, OpenRouterKlingClient)


def test_build_video_provider_rejects_unknown_model():
    ai_cfg = _AiGenCfg("unknown-vendor/some-model")
    try:
        build_video_provider(ai_cfg, api_key="sk-or-v1-test")
        assert False, "expected ValueError for an unsupported model id"
    except ValueError as exc:
        assert "unknown-vendor/some-model" in str(exc)


def test_production_seam_gen_run_uses_the_factory():
    """gen_run.py must call build_video_provider (not a hardcoded client)
    at the ai_video generation seam — this is the regression guard for the
    bug this ticket closes."""
    import src.gen_run as gen_run

    assert gen_run.build_video_provider is build_video_provider


# ---------------------------------------------------------------------------
# Problem 3 — cost projection derived from the CONFIGURED provider's rate
# ---------------------------------------------------------------------------


def test_seedance_four_second_shot_projects_22_cents():
    ai_cfg = _AiGenCfg("bytedance/seedance-2.0-fast")
    assert estimate_shot_cost_cents(ai_cfg, duration_s=4) == 22


def test_kling_shot_falls_back_to_flat_estimate():
    from src.ai_gen.runner import DEFAULT_SHOT_COST_ESTIMATE_CENTS

    ai_cfg = _AiGenCfg("kwaivgi/kling-v3.0-std")
    assert estimate_shot_cost_cents(ai_cfg, duration_s=4) == DEFAULT_SHOT_COST_ESTIMATE_CENTS


def test_malformed_config_does_not_crash_the_estimate():
    """A test double / partially-configured cfg (no .model set) must not
    raise — it degrades to the flat historical estimate."""
    from src.ai_gen.runner import DEFAULT_SHOT_COST_ESTIMATE_CENTS

    assert estimate_shot_cost_cents(MagicMock().ai_gen) == DEFAULT_SHOT_COST_ESTIMATE_CENTS


def test_five_clips_per_week_against_800c_ceiling_is_affordable():
    """~88c/Clip (per ADR-0009: 4 stills ~2c + 16s Seedance ~86c) x 5
    Clips/week ~= $4.40, comfortably under the 800c weekly ceiling."""
    cfg = load_config(str(ROOT / "config.yaml"))
    clips_per_week = cfg.clips_per_day * len(cfg.upload_weekdays)
    seedance_video_cost = 4 * estimate_shot_cost_cents(cfg.ai_gen, duration_s=4)  # 4 shots/clip
    projected_weekly_cents = clips_per_week * seedance_video_cost
    assert projected_weekly_cents <= cfg.ai_gen.weekly_spend_cents_ceiling


# ---------------------------------------------------------------------------
# bootstrap --check: unreachable configured model id fails clearly
# ---------------------------------------------------------------------------


class _BootstrapAiGenCfg:
    model = "bytedance/seedance-2.0-fast"
    still_model = "google/gemini-3.1-flash-image"


class _BootstrapCfg:
    ai_gen = _BootstrapAiGenCfg()


def test_bootstrap_check_fails_when_configured_model_unreachable(monkeypatch, capsys):
    from src import bootstrap

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + "0" * 64)

    catalog_response = MagicMock()
    catalog_response.raise_for_status = MagicMock()
    catalog_response.json.return_value = {
        "data": [{"id": "some-other-vendor/other-model"}]
    }
    with patch("requests.get", return_value=catalog_response):
        result = bootstrap.check_video_still_models_reachable(_BootstrapCfg())

    assert result is False
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "models-reachable" in out


def test_bootstrap_check_passes_when_configured_models_reachable(monkeypatch, capsys):
    from src import bootstrap

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + "0" * 64)

    catalog_response = MagicMock()
    catalog_response.raise_for_status = MagicMock()
    catalog_response.json.return_value = {
        "data": [
            {"id": "bytedance/seedance-2.0-fast"},
            {"id": "google/gemini-3.1-flash-image"},
        ]
    }
    with patch("requests.get", return_value=catalog_response):
        result = bootstrap.check_video_still_models_reachable(_BootstrapCfg())

    assert result is True
    out = capsys.readouterr().out
    assert "OK" in out


def test_bootstrap_check_is_offline_safe_without_key(monkeypatch, capsys):
    """No OPENROUTER_API_KEY -> skipped (True), zero network calls made."""
    from src import bootstrap

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with patch("requests.get") as p_get:
        result = bootstrap.check_video_still_models_reachable(_BootstrapCfg())

    assert result is True
    p_get.assert_not_called()


# ---------------------------------------------------------------------------
# Docs — CONTEXT.md defines the two new ADR-0009 glossary terms
# ---------------------------------------------------------------------------


def test_context_glossary_defines_generated_still_and_still_provider():
    text = (ROOT / "CONTEXT" / "CONTEXT.md").read_text(encoding="utf-8")
    assert "**Generated still**" in text
    assert "**Still provider**" in text
