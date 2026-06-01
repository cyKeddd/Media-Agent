"""FastAPI app for the dashboard (read + review file moves)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.dashboard.alerts_parser import parse_alerts_tail
from src.dashboard.review_action import ActionResult, ReviewAction, apply_review_action
from src.dashboard.scanner import scan_output_dirs
from src.dashboard.view_model import AlertView, build_dashboard_view, view_to_json


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


def _alerts_for_view(cfg) -> list[AlertView]:
    if cfg is None:
        return []
    alerts_path = cfg.abs_path(cfg.paths.logs_dir) / "alerts.md"
    return [
        AlertView(
            timestamp=a.timestamp,
            kind=a.kind,
            message=a.message,
            severity=a.severity,
        )
        for a in parse_alerts_tail(alerts_path)
    ]


def _build_view(cfg, reader, output_root: Path):
    scan = scan_output_dirs(output_root)
    tz = ZoneInfo(cfg.timezone)
    return build_dashboard_view(
        reader,
        scan,
        now=datetime.now(tz),
        tz=tz,
        ai_gen=cfg.ai_gen,
        output_root=output_root,
        recent_alerts=_alerts_for_view(cfg),
        human_review=bool(getattr(cfg, "human_review", True)),
    )


def _action_response(result: ActionResult) -> dict:
    return {
        "ok": result.ok,
        "refused": result.refused,
        "message": result.message,
        "clip_id": result.clip_id,
        "action": result.action.value,
        "from_subdir": result.from_subdir,
        "to_subdir": result.to_subdir,
    }


class ReviewBody(BaseModel):
    confirm: bool = False


def create_app(*, cfg=None, reader=None, output_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Media Agent Dashboard", docs_url=None, redoc_url=None)
    static_dir = Path(__file__).parent / "static"

    @app.get("/api/view")
    def api_view():
        if cfg is None or reader is None:
            raise HTTPException(status_code=503, detail="dashboard not configured")
        root = output_root or _output_root(cfg)
        return view_to_json(_build_view(cfg, reader, root))

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

    def _require_human_review():
        if cfg is None:
            raise HTTPException(status_code=503, detail="dashboard not configured")
        if not getattr(cfg, "human_review", True):
            raise HTTPException(status_code=403, detail="human_review is disabled")

    def _do_action(clip_id: str, action: ReviewAction, body: ReviewBody):
        _require_human_review()
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        root = output_root or _output_root(cfg)
        scan = scan_output_dirs(root)
        result = apply_review_action(clip_id, action, scan=scan, output_root=root)
        status = 200 if result.ok else (409 if result.refused else 500)
        from fastapi.responses import JSONResponse
        return JSONResponse(_action_response(result), status_code=status)

    @app.post("/api/clip/{clip_id}/approve")
    def api_approve(clip_id: str, body: ReviewBody):
        return _do_action(clip_id, ReviewAction.approve, body)

    @app.post("/api/clip/{clip_id}/reject")
    def api_reject(clip_id: str, body: ReviewBody):
        return _do_action(clip_id, ReviewAction.reject, body)

    @app.post("/api/clip/{clip_id}/unreject")
    def api_unreject(clip_id: str, body: ReviewBody):
        return _do_action(clip_id, ReviewAction.unreject, body)

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
