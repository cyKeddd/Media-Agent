"""One-shot cleanup of known duplicate pending copies for published clips."""

from __future__ import annotations

from pathlib import Path

ORPHANS = (
    "2026-06-02__slot_0900__genetic_leap_reverse_aging_51fa.mp4",
    "2026-06-02__slot_0900__google_just_open_sourced_its_secret_weapon_ac07.mp4",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "output" / "pending"
    removed = 0
    for name in ORPHANS:
        path = root / name
        if path.is_file():
            path.unlink()
            removed += 1
            print(f"removed {path}")
    print(f"done: {removed} orphan(s) removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
