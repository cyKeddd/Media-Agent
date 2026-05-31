"""M1a — output-dir scanner for the read-only dashboard."""

from __future__ import annotations

from pathlib import Path

from src.dashboard.scanner import scan_output_dirs


def _tree(tmp_path: Path) -> Path:
    for sub in ("pending", "approved", "rejected", "dry_run"):
        (tmp_path / sub).mkdir(parents=True)
    return tmp_path


def test_unscheduled_pending_maps_clip_id(tmp_path):
    root = _tree(tmp_path)
    mp4 = root / "pending" / "__unscheduled__abc123__my_slug.mp4"
    mp4.write_bytes(b"fake")

    result = scan_output_dirs(root)

    assert result.by_clip_id["abc123"] == ("pending", mp4)
    assert result.by_slug["my_slug"] == ("pending", mp4)


def test_slot_named_file_maps_by_slug(tmp_path):
    root = _tree(tmp_path)
    mp4 = root / "pending" / "2026-06-02__slot_0900__genetic_leap_51fa.mp4"
    mp4.write_bytes(b"fake")

    result = scan_output_dirs(root)

    assert "genetic_leap_51fa" in result.by_slug
    assert result.by_slug["genetic_leap_51fa"] == ("pending", mp4)
    assert "abc123" not in result.by_clip_id


def test_ignores_non_mp4(tmp_path):
    root = _tree(tmp_path)
    (root / "pending" / "notes.txt").write_text("nope")
    (root / "pending" / "__unscheduled__x__y.mp4").write_bytes(b"ok")

    result = scan_output_dirs(root)

    assert len(result.by_clip_id) == 1
    assert len(result.by_slug) == 1


def test_clip_in_no_dir_not_mapped(tmp_path):
    root = _tree(tmp_path)

    result = scan_output_dirs(root)

    assert result.by_clip_id == {}
    assert result.by_slug == {}


def test_approved_takes_precedence_over_pending_same_slug(tmp_path):
    root = _tree(tmp_path)
    slug = "same_slug_abcd"
    pending = root / "pending" / f"2026-06-01__slot_0900__{slug}.mp4"
    approved = root / "approved" / f"2026-06-01__slot_0900__{slug}.mp4"
    pending.write_bytes(b"p")
    approved.write_bytes(b"a")

    result = scan_output_dirs(root)

    assert result.by_slug[slug] == ("approved", approved)
