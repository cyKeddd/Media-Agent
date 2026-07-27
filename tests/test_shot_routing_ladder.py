"""Issue 66 — image-first shot routing ladder (ADR-0009 / ADR-0003).

All providers here are fakes — no network I/O, no real spend. The point of
this suite is to prove the LADDER'S ORDERING and cost-ceiling enforcement,
not any specific provider's wire format (that is Issue 64/65's job).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ai_gen.base import GenerationStatus, ShotResult, UnsupportedFirstFrameError
from src.image_fetch.base import ImageAsset
from src.image_fetch.errors import LivingPersonEntityError
from src.image_gen.base import StillResult
from src.scripter.shot_router import (
    RUNG_GENERATED_I2V,
    RUNG_KEN_BURNS,
    RUNG_LICENSED_I2V,
    RUNG_TEXT_TO_VIDEO,
    ClipCostCeilingError,
    route_shot,
    route_shots,
)
from src.state import Repository, connect, initialize_schema


# ---------------------------------------------------------------------------
# Fakes — no real spend, no network.
# ---------------------------------------------------------------------------


class FakeStillProvider:
    provider_name = "fake_still"

    def __init__(self, *, succeed=True, cost_cents=1, order_log=None, repo=None):
        self.calls = []
        self.succeed = succeed
        self.cost_cents = cost_cents
        self.order_log = order_log
        # Mirrors NanoBananaProvider's real contract (src/image_gen/nano_banana.py):
        # a StillProvider records its OWN spend into the 'openrouter_still'
        # bucket when given a repo + script_id; the ladder never double-records it.
        self.repo = repo

    def generate(self, prompt, *, aspect_ratio="9:16", dest, script_id=None):
        if self.order_log is not None:
            self.order_log.append("still_provider:generate")
        self.calls.append({"prompt": prompt, "dest": dest, "script_id": script_id})
        if not self.succeed:
            raise RuntimeError("fake still generation failed")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-still-png")
        if self.repo is not None and script_id is not None:
            self.repo.quota_record(
                "openrouter_still", self.cost_cents, provider="openrouter",
                script_id=script_id,
            )
        return StillResult(path=dest, cost_cents=self.cost_cents, raw={})


class FakeVideoProvider:
    provider_name = "fake_video"

    def __init__(self, *, unsupported_first_frame=False, cost_cents=67, fail=False):
        self.submit_calls = []
        self.download_calls = []
        self.unsupported_first_frame = unsupported_first_frame
        self.cost_cents = cost_cents
        self.fail = fail

    def submit(self, prompt, *, duration_s=5, aspect_ratio="9:16", first_frame_path=None):
        self.submit_calls.append(
            {"prompt": prompt, "first_frame_path": first_frame_path}
        )
        if first_frame_path is not None and self.unsupported_first_frame:
            raise UnsupportedFirstFrameError("fake_video: no i2v support")
        return "ext-1"

    def wait_for_completion(self, external_id, *, poll_interval_s=15, timeout_s=600):
        if self.fail:
            return ShotResult(
                external_id=external_id, status=GenerationStatus.FAILED, error="boom",
            )
        return ShotResult(
            external_id=external_id,
            status=GenerationStatus.SUCCEEDED,
            download_url="http://fake/video.mp4",
            cost_cents=self.cost_cents,
        )

    def download(self, url, dest):
        self.download_calls.append({"url": url, "dest": dest})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-video")
        return dest


def _fake_ken_burns(order_log=None):
    calls = []

    def _render(still_path: Path, dest: Path) -> Path:
        if order_log is not None:
            order_log.append("ken_burns:render")
        calls.append({"still_path": still_path, "dest": dest})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-ken-burns")
        return dest

    _render.calls = calls
    return _render


def _make_licensed_resolver(order_log, *, hit: bool):
    calls = []

    def _resolver(entity, query):
        order_log.append(f"licensed:{entity}")
        calls.append({"entity": entity, "query": query})
        if hit:
            return ImageAsset(
                path=f"/cache/{entity.replace(' ', '_')}.jpg",
                source="logo", license="CC0", source_url="https://x",
                width=1080, height=1920,
            )
        return None

    _resolver.calls = calls
    return _resolver


def _repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _real_image_shot(entity="RTX 5090", duration_s=4):
    return {"kind": "real_image", "entity": entity, "duration_s": duration_s}


def _ai_video_shot(prompt="abstract data flow", duration_s=4):
    return {"kind": "ai_video", "prompt": prompt, "duration_s": duration_s}


# ---------------------------------------------------------------------------
# Ladder ordering — INV-7
# ---------------------------------------------------------------------------


def test_licensed_hit_uses_licensed_i2v_and_never_calls_still_provider(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=True)
    still = FakeStillProvider(order_log=order)
    video = FakeVideoProvider()

    routed = route_shot(
        _real_image_shot(), 0, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
    )

    assert routed.rung == RUNG_LICENSED_I2V
    assert len(licensed.calls) == 1
    assert len(still.calls) == 0  # still provider must never be called on a hit
    assert video.submit_calls[0]["first_frame_path"] is not None
    assert routed.path.exists()


def test_licensed_miss_falls_through_to_generated_still_with_ordering_proof(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=False)
    still = FakeStillProvider(order_log=order)
    video = FakeVideoProvider()

    routed = route_shot(
        _real_image_shot(), 0, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
    )

    assert routed.rung == RUNG_GENERATED_I2V
    assert len(licensed.calls) == 1
    assert len(still.calls) == 1
    # THE ordering assertion the ticket demands: licensed lookup attempted
    # and OBSERVED TO MISS strictly before the still provider is invoked.
    assert order == ["licensed:RTX 5090", "still_provider:generate"]
    assert order.index("licensed:RTX 5090") < order.index("still_provider:generate")


def test_shot_naming_no_real_entity_skips_licensed_lookup(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=True)
    still = FakeStillProvider(order_log=order)
    video = FakeVideoProvider()

    routed = route_shot(
        _ai_video_shot(), 0, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
    )

    assert routed.rung == RUNG_GENERATED_I2V
    assert len(licensed.calls) == 0
    assert len(still.calls) == 1


# ---------------------------------------------------------------------------
# Fallbacks — INV-12
# ---------------------------------------------------------------------------


def test_still_generation_failure_falls_back_to_text_to_video_and_completes(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=False)
    still = FakeStillProvider(succeed=False, order_log=order)
    video = FakeVideoProvider()

    routed = route_shot(
        _real_image_shot(), 0, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
    )

    assert routed.rung == RUNG_TEXT_TO_VIDEO
    assert video.submit_calls[0]["first_frame_path"] is None
    assert routed.path.exists()  # the Clip still completes


def test_image_to_video_unavailable_falls_back_to_ken_burns(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=True)
    still = FakeStillProvider(order_log=order)
    video = FakeVideoProvider(unsupported_first_frame=True)
    ken_burns = _fake_ken_burns(order_log=order)

    routed = route_shot(
        _real_image_shot(), 0, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=ken_burns,
    )

    assert routed.rung == RUNG_KEN_BURNS
    assert len(ken_burns.calls) == 1
    assert ken_burns.calls[0]["still_path"] == routed.still_path
    assert routed.path.exists()


# ---------------------------------------------------------------------------
# Persistence / evidence
# ---------------------------------------------------------------------------


def test_rung_is_persisted_per_shot_and_readable_for_evidence(tmp_path):
    order: list[str] = []
    licensed = _make_licensed_resolver(order, hit=True)
    still = FakeStillProvider(order_log=order)
    video = FakeVideoProvider()

    shots = [_real_image_shot("OpenAI logo"), _ai_video_shot("server room lights")]
    routed = route_shots(
        shots, tmp_path,
        licensed_resolver=licensed,
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
    )

    assert [r.rung for r in routed] == [RUNG_LICENSED_I2V, RUNG_GENERATED_I2V]

    import json
    manifest = json.loads((tmp_path / "routing.json").read_text(encoding="utf-8"))
    assert [m["rung"] for m in manifest] == [RUNG_LICENSED_I2V, RUNG_GENERATED_I2V]
    assert manifest[0]["index"] == 0
    assert manifest[1]["index"] == 1


# ---------------------------------------------------------------------------
# Directed scripts — ADR-0008, no exemption
# ---------------------------------------------------------------------------


def test_directed_script_shot_traverses_the_identical_ladder(tmp_path):
    """A Directed script (ADR-0008) hands the ladder ordinary shot dicts
    tagged with extra director metadata; there is no branch in route_shot
    keyed on that metadata, so the outcome is identical to an undirected
    shot with the same kind/entity."""
    order_plain: list[str] = []
    order_directed: list[str] = []

    plain_shot = _real_image_shot("RTX 5090")
    directed_shot = {
        **_real_image_shot("RTX 5090"),
        "director": "hermes",
        "directed": True,
        "shot_source": "hermes_director",
    }

    routed_plain = route_shot(
        plain_shot, 0, tmp_path / "plain",
        licensed_resolver=_make_licensed_resolver(order_plain, hit=False),
        still_provider=FakeStillProvider(order_log=order_plain),
        video_provider=FakeVideoProvider(),
        ken_burns_render=_fake_ken_burns(),
    )
    routed_directed = route_shot(
        directed_shot, 0, tmp_path / "directed",
        licensed_resolver=_make_licensed_resolver(order_directed, hit=False),
        still_provider=FakeStillProvider(order_log=order_directed),
        video_provider=FakeVideoProvider(),
        ken_burns_render=_fake_ken_burns(),
    )

    assert routed_plain.rung == routed_directed.rung == RUNG_GENERATED_I2V
    assert order_plain == order_directed == [
        "licensed:RTX 5090", "still_provider:generate",
    ]


# ---------------------------------------------------------------------------
# INV-8 — living person guard, before any billable call
# ---------------------------------------------------------------------------


def test_shot_naming_living_person_rejected_before_any_billable_call(tmp_path):
    licensed = _make_licensed_resolver([], hit=True)
    still = FakeStillProvider()
    video = FakeVideoProvider()

    shot = {"kind": "ai_video", "prompt": "photo of Tim Cook holding the new iPhone", "duration_s": 4}

    with pytest.raises(LivingPersonEntityError):
        route_shot(
            shot, 0, tmp_path,
            licensed_resolver=licensed,
            still_provider=still,
            video_provider=video,
            ken_burns_render=_fake_ken_burns(),
            living_person_patterns=["photo of"],
        )

    assert len(licensed.calls) == 0
    assert len(still.calls) == 0
    assert len(video.submit_calls) == 0


# ---------------------------------------------------------------------------
# INV-2 — combined per-clip ceiling, checked before EACH billable call
# ---------------------------------------------------------------------------


def test_combined_ceiling_blocks_still_generation_before_the_call(tmp_path):
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 145, provider="openrouter", script_id="clip-1")

    licensed = _make_licensed_resolver([], hit=False)
    still = FakeStillProvider(cost_cents=10)
    video = FakeVideoProvider()

    with pytest.raises(ClipCostCeilingError, match="per_clip_cost_cents_max"):
        route_shot(
            _real_image_shot(), 0, tmp_path,
            licensed_resolver=licensed,
            still_provider=still,
            video_provider=video,
            ken_burns_render=_fake_ken_burns(),
            script_id="clip-1",
            repo=repo,
            per_clip_cost_cents_max=150,
            still_cost_estimate_cents=10,
        )

    assert len(still.calls) == 0  # refused BEFORE the call, not after


def test_combined_ceiling_blocks_video_submission_before_the_call(tmp_path):
    """A Clip already carrying still spend must not be pushed over 150c by
    the video (i2v/text-to-video) call either — same combined bucket."""
    repo = _repo(tmp_path)
    repo.quota_record("openrouter_still", 145, provider="openrouter", script_id="clip-2")

    licensed = _make_licensed_resolver([], hit=False)
    video = FakeVideoProvider(cost_cents=67)

    with pytest.raises(ClipCostCeilingError, match="per_clip_cost_cents_max"):
        route_shot(
            _ai_video_shot(), 0, tmp_path,
            licensed_resolver=licensed,
            still_provider=None,  # no still step at all -> straight to video
            video_provider=video,
            ken_burns_render=_fake_ken_burns(),
            script_id="clip-2",
            repo=repo,
            per_clip_cost_cents_max=150,
            video_cost_estimate_cents=10,
        )

    assert len(video.submit_calls) == 0  # refused BEFORE the call, not after


def test_combined_ceiling_counts_both_still_and_video_buckets(tmp_path):
    """quota_script_total sums BOTH endpoint='openrouter' (video) and
    endpoint='openrouter_still' rows — the exact gap the parent flagged."""
    repo = _repo(tmp_path)
    repo.quota_record("openrouter", 80, provider="openrouter", script_id="clip-3")
    repo.quota_record("openrouter_still", 65, provider="openrouter", script_id="clip-3")
    # combined = 145; one more still (10c) would push to 155 > 150.

    still = FakeStillProvider(cost_cents=10)

    with pytest.raises(ClipCostCeilingError):
        route_shot(
            _real_image_shot(), 0, tmp_path,
            licensed_resolver=_make_licensed_resolver([], hit=False),
            still_provider=still,
            video_provider=FakeVideoProvider(),
            ken_burns_render=_fake_ken_burns(),
            script_id="clip-3",
            repo=repo,
            per_clip_cost_cents_max=150,
            still_cost_estimate_cents=10,
        )

    assert len(still.calls) == 0


def test_video_and_still_spend_recorded_and_readable_after_success(tmp_path):
    repo = _repo(tmp_path)
    still = FakeStillProvider(cost_cents=1, repo=repo)
    video = FakeVideoProvider(cost_cents=67)

    route_shot(
        _real_image_shot(), 0, tmp_path,
        licensed_resolver=_make_licensed_resolver([], hit=False),
        still_provider=still,
        video_provider=video,
        ken_burns_render=_fake_ken_burns(),
        script_id="clip-4",
        repo=repo,
        per_clip_cost_cents_max=150,
    )

    # The still provider records its own spend (Issue 64 contract, mirrored
    # by the fake); the ladder records the video spend. quota_script_total
    # sums BOTH buckets, so the combined total is exact and readable.
    assert repo.quota_script_total("clip-4") == 68
