"""M4 — dashboard review-action module (file moves only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dashboard.review_action import ReviewAction, apply_review_action
from src.dashboard.scanner import scan_output_dirs


def _tree(tmp_path: Path):
    root = tmp_path / "output"
    for sub in ("pending", "approved", "rejected"):
        (root / sub).mkdir(parents=True)
    return root


def test_approve_moves_pending_to_approved(tmp_path):
    root = _tree(tmp_path)
    clip_id = "clip-approve"
    pending = root / "pending" / f"__unscheduled__{clip_id}__slug.mp4"
    pending.write_bytes(b"mp4")
    scan = scan_output_dirs(root)
    result = apply_review_action(
        clip_id, ReviewAction.approve, scan=scan, output_root=root,
    )
    assert result.ok is True
    assert (root / "approved" / pending.name).is_file()
    assert not pending.exists()


def test_reject_moves_pending_to_rejected(tmp_path):
    root = _tree(tmp_path)
    clip_id = "clip-reject"
    pending = root / "pending" / f"__unscheduled__{clip_id}__slug.mp4"
    pending.write_bytes(b"mp4")
    scan = scan_output_dirs(root)
    result = apply_review_action(clip_id, ReviewAction.reject, scan=scan, output_root=root)
    assert result.ok is True
    assert (root / "rejected" / pending.name).is_file()


def test_unreject_moves_rejected_to_pending(tmp_path):
    root = _tree(tmp_path)
    clip_id = "clip-unreject"
    name = f"__unscheduled__{clip_id}__slug.mp4"
    rejected = root / "rejected" / name
    rejected.write_bytes(b"mp4")
    scan = scan_output_dirs(root)
    result = apply_review_action(clip_id, ReviewAction.unreject, scan=scan, output_root=root)
    assert result.ok is True
    assert (root / "pending" / name).is_file()


def test_refuses_when_not_in_pending(tmp_path):
    root = _tree(tmp_path)
    clip_id = "clip-approved"
    approved = root / "approved" / f"2026-06-04__slot_0900__slug.mp4"
    approved.write_bytes(b"mp4")
    scan = scan_output_dirs(root)
    scan.by_clip_id[clip_id] = ("approved", approved)
    result = apply_review_action(clip_id, ReviewAction.approve, scan=scan, output_root=root)
    assert result.ok is False
    assert result.refused is True
    assert approved.exists()
