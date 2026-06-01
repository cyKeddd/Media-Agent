"""Approve / Reject actions — atomic file moves inside output/ only (ADR-0006)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.dashboard.scanner import ScanResult


class ReviewAction(str, Enum):
    approve = "approve"
    reject = "reject"
    unreject = "unreject"


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    refused: bool
    message: str
    clip_id: str
    action: ReviewAction
    from_subdir: str | None = None
    to_subdir: str | None = None


def _dest_for(action: ReviewAction, filename: str, root: Path) -> Path:
    if action == ReviewAction.approve:
        return root / "approved" / filename
    if action == ReviewAction.reject:
        return root / "rejected" / filename
    if action == ReviewAction.unreject:
        return root / "pending" / filename
    raise ValueError(f"unknown action: {action}")


def apply_review_action(
    clip_id: str,
    action: ReviewAction,
    *,
    scan: ScanResult,
    output_root: Path,
) -> ActionResult:
    """Move a clip's MP4 between output subdirs; no DB write."""
    required_subdir = "pending" if action in (ReviewAction.approve, ReviewAction.reject) else "rejected"
    located = scan.by_clip_id.get(clip_id)
    if located is None:
        return ActionResult(
            ok=False,
            refused=True,
            message=f"clip {clip_id} has no file on disk",
            clip_id=clip_id,
            action=action,
        )
    subdir, src_path = located
    if subdir != required_subdir:
        return ActionResult(
            ok=False,
            refused=True,
            message=f"clip {clip_id} is in {subdir}/, not {required_subdir}/",
            clip_id=clip_id,
            action=action,
            from_subdir=subdir,
        )
    dest = _dest_for(action, src_path.name, output_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src_path, dest)
    except OSError as exc:
        return ActionResult(
            ok=False,
            refused=False,
            message=str(exc),
            clip_id=clip_id,
            action=action,
            from_subdir=subdir,
        )
    to_subdir = dest.parent.name
    return ActionResult(
        ok=True,
        refused=False,
        message=f"moved to {to_subdir}/",
        clip_id=clip_id,
        action=action,
        from_subdir=subdir,
        to_subdir=to_subdir,
    )
