"""Config-driven video provider factory (ADR-0009 / Issue 67 / INV-10).

Problem this closes: `src/gen_run.py` used to construct
`OpenRouterKlingClient` directly at its one production call site, so
flipping `ai_gen.model` in config.yaml had NO effect on which provider
actually ran — INV-10 ("reverting to Kling is a config-only change") was
unproven and, in fact, false. `build_video_provider()` is the single seam
gen_run.py must call instead: the SAME api_key with a DIFFERENT
`ai_cfg.model` value yields a different concrete Provider class, with zero
other code changes.

`estimate_shot_cost_cents()` closes a related problem: the pre-billing
weekly/per-clip cost projection used to be a flat module constant tuned for
Kling's price. Once the default flips to Seedance (~5.38c/s, ~22c for a 4s
shot) a Kling-shaped constant over-estimates by ~3x, which fails SAFE (it
refuses spend it shouldn't) but silently strangles throughput — the same
"why did the channel stop producing" signature as the original outage this
project is recovering from. The estimate is derived from the CONFIGURED
provider's rate instead.
"""

from __future__ import annotations

import math

from .base import Provider
from .openrouter_kling import OpenRouterKlingClient
from .openrouter_seedance import OpenRouterSeedanceClient
from .runner import DEFAULT_SHOT_COST_ESTIMATE_CENTS

_SEEDANCE_PREFIX = "bytedance/"
_KLING_PREFIX = "kwaivgi/"


def build_video_provider(ai_cfg, api_key: str | None) -> Provider:
    """Construct the video Provider named by ``ai_cfg.model``.

    INV-10: reverting from Seedance to Kling (or vice versa) is a
    config-only change — flip ``ai_gen.model`` in config.yaml and this
    factory returns a different class. No other code changes.
    """
    model = ai_cfg.model
    if model.startswith(_SEEDANCE_PREFIX):
        return OpenRouterSeedanceClient(
            api_key=api_key,
            model=model,
            rate_cents_per_second=ai_cfg.seedance_rate_cents_per_second,
        )
    if model.startswith(_KLING_PREFIX):
        return OpenRouterKlingClient(api_key=api_key, model=model)
    raise ValueError(f"build_video_provider: unsupported ai_gen.model {model!r}")


def estimate_shot_cost_cents(ai_cfg, duration_s: int = 4) -> int:
    """Pre-billing per-shot cost projection, derived from the CONFIGURED
    provider's rate instead of a flat module constant (Issue 67).

    Seedance bills per-second: projected from
    ``ai_cfg.seedance_rate_cents_per_second * duration_s``, rounded up
    (never under-estimates — INV-1/INV-2 must fail safe). Any other
    configured model (Kling today) has no per-second rate in config — its
    actual cost is read back from the provider's reported ``usage.cost``
    after the call — so it falls back to the historical flat
    ``DEFAULT_SHOT_COST_ESTIMATE_CENTS`` estimate.

    Defensive on a malformed/stubbed config (e.g. a bare ``MagicMock()`` in
    a test double that never set ``.model``): anything that isn't a plain
    ``str`` model id is treated as "not Seedance" and falls back to the
    constant rather than raising.
    """
    model = getattr(ai_cfg, "model", None)
    if isinstance(model, str) and model.startswith(_SEEDANCE_PREFIX):
        rate = getattr(ai_cfg, "seedance_rate_cents_per_second", None)
        if isinstance(rate, (int, float)):
            return math.ceil(duration_s * rate)
    return DEFAULT_SHOT_COST_ESTIMATE_CENTS
