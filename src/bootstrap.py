"""
Phase 0 environment health check + Phase 6 end-to-end smoke test.

Usage:
    python -m src.bootstrap --check                         # verify env (Phase 0)
    python -m src.bootstrap --init-db                       # create state.db with full schema
    python -m src.bootstrap --smoke --keyword "<keyword>"   # Phase 6 single-keyword smoke
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from src.config_loader import load_config
from src.state import Repository, connect, initialize_schema

# Project root — used to locate .env (Issue 59). Same pattern as
# src/gen_run.py and src/daily_upload.py.
ROOT = Path(__file__).resolve().parent.parent

OPENROUTER_KEY_PATTERN = re.compile(r"^sk-or-v1-[0-9a-f]{64}$")


def load_env_file(root: Path = ROOT) -> None:
    """Load `.env` into os.environ, without clobbering variables the real
    environment already set. A missing .env file is not an error — the env
    may legitimately be populated by the shell/scheduler."""
    load_dotenv(root / ".env", override=False)


def _ok(name: str, detail: str = "") -> bool:
    print(f"  OK   {name}" + (f"  ({detail})" if detail else ""))
    return True


def _fail(name: str, reason: str) -> bool:
    print(f"  FAIL {name}: {reason}")
    return False


def check_python() -> bool:
    if sys.version_info < (3, 11):
        return _fail("python", f"need 3.11+, got {sys.version_info.major}.{sys.version_info.minor}")
    return _ok("python", f"{sys.version_info.major}.{sys.version_info.minor}")


def check_ffmpeg() -> bool:
    path = shutil.which("ffmpeg")
    if not path:
        return _fail("ffmpeg", "not on PATH")
    try:
        out = subprocess.check_output([path, "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        return _fail("ffmpeg", f"failed to query encoders: {e}")
    has_nvenc = "h264_nvenc" in out
    if not has_nvenc:
        return _fail("ffmpeg-nvenc", "h264_nvenc encoder not present (CPU fallback would be slow)")
    return _ok("ffmpeg", f"{path}, h264_nvenc available")


def check_yt_dlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError as e:
        return _fail("yt-dlp", str(e))
    return _ok("yt-dlp")


def check_faster_whisper(device: str) -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError as e:
        return _fail("faster-whisper", str(e))
    if device == "cuda":
        try:
            import ctranslate2  # noqa: F401
            cuda_count = ctranslate2.get_cuda_device_count()
        except Exception as e:
            return _fail("faster-whisper-cuda", f"ctranslate2 import failed: {e}")
        if cuda_count == 0:
            return _fail("faster-whisper-cuda", "0 CUDA devices visible — install CUDA 12.x + cuDNN 9")
        return _ok("faster-whisper", f"CUDA devices={cuda_count}")
    return _ok("faster-whisper", "CPU mode")


def check_ollama(host: str, model: str) -> bool:
    try:
        import requests
    except ImportError as e:
        return _fail("ollama", f"requests not installed: {e}")
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
    except Exception as e:
        return _fail("ollama", f"cannot reach {host} ({e}); install from https://ollama.com")
    models = [m.get("name", "") for m in r.json().get("models", [])]
    if not any(m.startswith(model.split(":")[0]) for m in models):
        return _fail(
            "ollama-model",
            f"{model} not pulled; run `ollama pull {model}`. Have: {models}",
        )
    return _ok("ollama", f"host={host}, model={model}")


def check_youtube_oauth(client_secrets: Path, oauth_token: Path) -> bool:
    if not client_secrets.exists():
        return _fail(
            "youtube-oauth",
            f"{client_secrets} missing — download OAuth Desktop client from Google Cloud Console",
        )
    if not oauth_token.exists():
        return _fail(
            "youtube-oauth",
            f"{oauth_token} missing — first-time auth not yet run (Phase 5 task)",
        )
    return _ok("youtube-oauth", "client_secrets + cached token present")


def check_espeak_ng() -> bool:
    path = shutil.which("espeak-ng") or shutil.which("espeak")
    if not path:
        return _fail(
            "espeak-ng",
            "not on PATH — required for Kokoro; install espeak-ng for Windows",
        )
    return _ok("espeak-ng", path)


def check_kokoro() -> bool:
    try:
        import kokoro  # noqa: F401
    except ImportError:
        return _fail("kokoro", "pip install kokoro soundfile (Pivot.7 narration engine)")
    return _ok("kokoro")


def check_copyright_acknowledgement(cfg) -> bool:
    """Pivot.0 added copyright_acknowledgement as an optional ack of the
    elevated movie-clip strike risk. Surface as a soft warning in --check;
    not a hard failure."""
    ack = getattr(cfg, "copyright_acknowledgement", None)
    if not ack:
        print("  WARN copyright-ack: cfg.copyright_acknowledgement not set "
              "(hybrid real-image licensing risk unacknowledged)")
        return True
    return _ok("copyright-ack", f"value={ack!r}")


def check_openrouter_key() -> bool:
    """Issue 59 — a bad OPENROUTER_API_KEY must fail loudly at check time,
    not silently at billing time. Never echo the key value; report a length
    and prefix only, and distinguish absent from malformed."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return _fail("openrouter-api-key", "OPENROUTER_API_KEY is not set (absent)")
    if not OPENROUTER_KEY_PATTERN.match(key):
        # Never slice/echo the actual secret — only report whether it starts
        # with the expected literal prefix, plus a length.
        starts_ok = key.startswith("sk-or-v1-")
        prefix_desc = "sk-or-v1-..." if starts_ok else "<unexpected prefix>"
        return _fail(
            "openrouter-api-key",
            f"malformed — expected ^sk-or-v1-[0-9a-f]{{64}}$, got "
            f"prefix={prefix_desc} len={len(key)}",
        )
    return _ok("openrouter-api-key", f"len={len(key)}, prefix='sk-or-v1-...'")


def check_video_still_models_reachable(cfg) -> bool:
    """Issue 67 — the configured video (`ai_gen.model`) and still
    (`ai_gen.still_model`) model ids must be present on OpenRouter's live
    model catalog. A check-time failure here is far cheaper than a Sunday
    02:00 failure mid-run.

    Offline-safe: SKIPPED (not failed) when OPENROUTER_API_KEY is absent —
    `check_openrouter_key()` already reports that failure distinctly, so
    this check would otherwise just be a redundant duplicate failure. Tests
    monkeypatch `requests.get` so no live network call is made in CI."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print(
            "  SKIP models-reachable: OPENROUTER_API_KEY not set "
            "(see openrouter-api-key check)"
        )
        return True
    video_model = cfg.ai_gen.model
    still_model = cfg.ai_gen.still_model
    try:
        import requests
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        available = {m.get("id") for m in resp.json().get("data", [])}
    except Exception as exc:
        return _fail(
            "models-reachable",
            f"could not reach OpenRouter model catalog: {exc}",
        )
    missing = [m for m in (video_model, still_model) if m not in available]
    if missing:
        return _fail(
            "models-reachable",
            f"configured model id(s) not found in OpenRouter catalog: {missing}",
        )
    return _ok("models-reachable", f"video={video_model!r}, still={still_model!r}")


def check_dirs(cfg) -> bool:
    needed = [
        cfg.abs_path(cfg.paths.raw_dir),
        cfg.abs_path(cfg.paths.transcripts_dir),
        cfg.abs_path(cfg.paths.pending_dir),
        cfg.abs_path(cfg.paths.approved_dir),
        cfg.abs_path(cfg.paths.rejected_dir),
        cfg.abs_path(cfg.paths.dry_run_dir),
        cfg.abs_path(cfg.paths.logs_dir),
    ]
    for d in needed:
        d.mkdir(parents=True, exist_ok=True)
    return _ok("project-dirs", f"{len(needed)} directories ready")


def init_db(cfg) -> None:
    db_path = cfg.abs_path(cfg.paths.state_db)
    conn = connect(db_path)
    initialize_schema(conn)
    conn.close()
    print(f"  OK   state.db initialized at {db_path}")


def run_checks(cfg) -> int:
    print("Media Agent — environment check\n")
    results: list[bool] = []
    results.append(check_python())
    results.append(check_dirs(cfg))
    results.append(check_ffmpeg())
    results.append(check_yt_dlp())
    results.append(check_faster_whisper(cfg.whisper_device))
    results.append(check_kokoro())
    results.append(check_espeak_ng())
    results.append(
        check_ollama(
            os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            cfg.ollama_model,
        )
    )
    results.append(
        check_youtube_oauth(
            cfg.abs_path(cfg.paths.client_secrets),
            cfg.abs_path(cfg.paths.oauth_token),
        )
    )
    results.append(check_copyright_acknowledgement(cfg))
    results.append(check_openrouter_key())
    results.append(check_video_still_models_reachable(cfg))
    failures = sum(1 for ok in results if not ok)
    print()
    if failures:
        print(f"{failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


def run_smoke(cfg, keyword: str) -> Dict[str, Any]:
    """Phase 6 end-to-end smoke test.

    Drives one keyword through the full pipeline against the configured test
    channel. Each stage's run_all is invoked (idempotent skips make this cheap
    when most work is done; first run will Whisper, render, and upload one
    clip).

    Returns a summary dict; raises on any stage failure so the CLI exits
    non-zero with a clear error.

    Stages (matches the Phase 6 plan):
      1. discovery.run_for_keyword(cfg, repo, ledger, youtube, keyword)
      2. downloader.run_all(cfg, repo)
      3. lang_detect.run_all(repo, cfg)
      4. selector.run_all(repo, cfg)
      5. policy_gate.run_all(repo, cfg, ollama_host=...)
      6. editor.run_all(repo, cfg)
      7. quality_screen.run_all(repo, cfg)
      8. Pick the first quality_pass clip with NULL publish_at_utc; upload it
         via uploader.upload_one_clip with explicit_publish_at=now+30min.
         (Bypasses slot_planner — smoke is a one-shot, not bulk slotting.)
    """
    from src import discovery, downloader, lang_detect, selector
    from src import policy_gate, editor, quality_screen
    from src.integrations.youtube import build_youtube_client
    from src.observability import setup_logging
    from src.quota_ledger import QuotaLedger
    from src.uploader.runner import UploadOutcome, upload_one_clip

    setup_logging(cfg.abs_path(cfg.paths.logs_dir))
    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        raise RuntimeError(
            f"state.db not found at {db_path}. "
            f"Run `python -m src.bootstrap --init-db` first."
        )

    conn = connect(db_path)
    repo = Repository(conn)
    youtube = build_youtube_client(cfg)
    ledger = QuotaLedger(repo.conn, ceiling_units=int(cfg.youtube_quota_ceiling_units))
    ollama_host = os.environ.get("OLLAMA_HOST")

    summary: Dict[str, Any] = {"keyword": keyword, "stages": {}}
    try:
        print(f"[smoke 1/8] discovery for '{keyword}'")
        kr = discovery.run_for_keyword(cfg, repo, ledger, youtube, keyword)
        summary["stages"]["discovery"] = {
            "inserted": kr.inserted, "fetched": kr.fetched, "skipped": kr.skipped,
        }

        print("[smoke 2/8] downloader")
        dl_results = downloader.run_all(cfg, repo)
        summary["stages"]["downloader"] = {"count": len(dl_results)}

        print("[smoke 3/8] lang_detect")
        lang_results = lang_detect.run_all(repo, cfg)
        summary["stages"]["lang_detect"] = {"count": len(lang_results)}

        print("[smoke 4/8] selector")
        sel_results = selector.run_all(repo, cfg)
        summary["stages"]["selector"] = {"count": len(sel_results)}

        print("[smoke 5/8] policy_gate")
        gate_results = policy_gate.run_all(repo, cfg, ollama_host=ollama_host)
        summary["stages"]["policy_gate"] = {"count": len(gate_results)}

        print("[smoke 6/8] editor")
        ed_results = editor.run_all(repo, cfg)
        summary["stages"]["editor"] = {"count": len(ed_results)}

        print("[smoke 7/8] quality_screen")
        qs_results = quality_screen.run_all(repo, cfg)
        summary["stages"]["quality_screen"] = {"count": len(qs_results)}

        # 8. Find the first quality_pass clip with NULL publish_at_utc and
        # upload it directly (bypassing slot_planner) with an explicit
        # publish_at = now + 30min.
        clip_row = repo.conn.execute(
            "SELECT clip_id FROM clips "
            "WHERE status='quality_pass' AND publish_at_utc IS NULL "
            "AND youtube_video_id IS NULL "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if clip_row is None:
            summary["stages"]["upload"] = {"skipped": "no quality_pass clip available"}
            print("[smoke 8/8] no quality_pass clip available; smoke ends here")
        else:
            clip_id = clip_row["clip_id"]
            target = datetime.now(timezone.utc) + timedelta(minutes=30)
            print(f"[smoke 8/8] uploader upload_one_clip({clip_id}, publishAt={target.isoformat()})")
            result = upload_one_clip(
                repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
                clip_id=clip_id,
                explicit_publish_at=target,
                ollama_host=ollama_host,
            )
            summary["stages"]["upload"] = {
                "clip_id": result.clip_id,
                "outcome": result.outcome.value,
                "youtube_video_id": result.youtube_video_id,
            }
            if result.outcome not in (UploadOutcome.uploaded,
                                      UploadOutcome.skipped_already_uploaded,
                                      UploadOutcome.dry_run):
                raise RuntimeError(
                    f"smoke upload failed: outcome={result.outcome.value} "
                    f"reason={result.reason!r}"
                )
        return summary
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="environment health check")
    parser.add_argument("--init-db", action="store_true", help="initialize state.db schema")
    parser.add_argument("--smoke", action="store_true",
                        help="Phase 6 end-to-end smoke test for one keyword")
    parser.add_argument("--keyword",
                        help="keyword for --smoke (required when --smoke is set)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    load_env_file()
    cfg = load_config(args.config)

    if args.init_db:
        init_db(cfg)
        return 0

    if args.smoke:
        if not args.keyword:
            print("--smoke requires --keyword", file=sys.stderr)
            return 2
        try:
            summary = run_smoke(cfg, args.keyword)
        except Exception as exc:
            print(f"smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        import json
        print(json.dumps(summary, indent=2))
        return 0

    if args.check or len(sys.argv) == 1:
        return run_checks(cfg)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
