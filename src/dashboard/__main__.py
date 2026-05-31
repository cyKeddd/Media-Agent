"""Launch the read-only dashboard on 127.0.0.1."""

from __future__ import annotations

import uvicorn

from src.config_loader import load_config
from src.dashboard.app import create_app
from src.dashboard.reader import build_reader
from src.state import Repository, connect, initialize_schema

HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    cfg = load_config()
    db_path = cfg.abs_path(cfg.paths.state_db)
    conn = connect(db_path)
    initialize_schema(conn)
    repo = Repository(conn)
    reader = build_reader(repo)
    app = create_app(cfg=cfg, reader=reader)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
