"""Scan output/ subdirs and map clips to their on-disk MP4 locations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SUBDIRS = ("pending", "approved", "rejected", "dry_run")
_SUBDIR_RANK = {"approved": 4, "pending": 3, "rejected": 2, "dry_run": 1}
_UNSCHEDULED_RE = re.compile(r"^__unscheduled__(?P<clip_id>.+?)__(?P<slug>.+)\.mp4$")
_SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}__slot_\d{4}__(?P<slug>.+)\.mp4$")


@dataclass(frozen=True)
class ScanResult:
    by_clip_id: dict[str, tuple[str, Path]]
    by_slug: dict[str, tuple[str, Path]]


def _extract_slug(filename: str) -> str | None:
    m = _UNSCHEDULED_RE.match(filename)
    if m:
        return m.group("slug")
    m = _SLOT_RE.match(filename)
    if m:
        return m.group("slug")
    if filename.endswith(".mp4"):
        return filename[:-4]
    return None


def scan_output_dirs(output_root: Path) -> ScanResult:
    """Return clip_id and slug indexes over pending/approved/rejected/dry_run."""
    by_clip_id: dict[str, tuple[str, Path]] = {}
    by_slug: dict[str, tuple[str, Path]] = {}

    for subdir in _SUBDIRS:
        dir_path = output_root / subdir
        if not dir_path.is_dir():
            continue
        for mp4 in dir_path.glob("*.mp4"):
            m = _UNSCHEDULED_RE.match(mp4.name)
            if m:
                by_clip_id[m.group("clip_id")] = (subdir, mp4)
            slug = _extract_slug(mp4.name)
            if slug is None:
                continue
            prev = by_slug.get(slug)
            if prev is None or _SUBDIR_RANK[subdir] > _SUBDIR_RANK[prev[0]]:
                by_slug[slug] = (subdir, mp4)

    return ScanResult(by_clip_id=by_clip_id, by_slug=by_slug)
