"""FastAPI app for the read-only dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.dashboard.scanner import scan_output_dirs
from src.dashboard.view_model import build_dashboard_view, view_to_json


def _output_root(cfg) -> Path:
    pending = cfg.abs_path(cfg.paths.pending_dir)
    return pending.parent


def _resolve_video_path(output_root: Path, relpath: str) -> Path:
    candidate = (output_root / relpath).resolve()
    root_resolved = output_root.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        raise HTTPException(status_code=403, detail="path outside output/")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return candidate


def create_app(*, cfg=None, reader=None, output_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Media Agent Dashboard", docs_url=None, redoc_url=None)
    static_dir = Path(__file__).parent / "static"

    @app.get("/api/view")
    def api_view():
        if cfg is None or reader is None:
            raise HTTPException(status_code=503, detail="dashboard not configured")
        root = output_root or _output_root(cfg)
        scan = scan_output_dirs(root)
        tz = ZoneInfo(cfg.timezone)
        view = build_dashboard_view(
            reader,
            scan,
            now=datetime.now(tz),
            tz=tz,
            ai_gen=cfg.ai_gen,
            output_root=root,
        )
        return view_to_json(view)

    @app.get("/api/video/{file_path:path}")
    def api_video(file_path: str):
        if cfg is None:
            raise HTTPException(status_code=503, detail="dashboard not configured")
        root = output_root or _output_root(cfg)
        target = _resolve_video_path(root, file_path)
        return FileResponse(
            target,
            media_type="video/mp4",
            filename=target.name,
        )

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
