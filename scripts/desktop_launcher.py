from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Movie Compass"
HOST = "127.0.0.1"
PORT = 8765


def bundled_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else Path(__file__).resolve().parents[1]


def application_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "MovieCompass"


def _copy_once(source: Path, destination: Path) -> None:
    if destination.exists() or not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def prepare_local_storage(resources: Path, local_root: Path) -> None:
    processed = local_root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for name in (
        "tmdb-rich-details.json",
        "display-metadata.json",
        "tmdb-catalog.sqlite3",
        "tmdb-catalog-manifest.json",
    ):
        _copy_once(resources / "data" / "bootstrap" / name, processed / name)
    _copy_once(resources / "ml" / "artifacts", local_root / "ml" / "artifacts")


def load_tmdb_key(local_root: Path) -> str:
    settings_path = local_root / "settings.env"
    if settings_path.is_file():
        for line in settings_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TMDB_API_KEY="):
                return line.partition("=")[2].strip()
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        value = simpledialog.askstring(
            APP_NAME,
            "Paste your TMDB API key. It is stored only on this computer.\n\n"
            "You can leave this blank and use the bundled offline catalog, but live title "
            "search, posters, and streaming updates will be limited.",
            show="*",
            parent=root,
        )
        root.destroy()
    except Exception:
        value = ""
    key = (value or "").strip()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(f"TMDB_API_KEY={key}\n", encoding="utf-8")
    return key


def configure_environment(resources: Path, local_root: Path) -> None:
    database = (local_root / "data" / "personal.sqlite3").as_posix()
    values = {
        "APP_ENV": "desktop",
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": f"sqlite+pysqlite:///{database}",
        "TMDB_API_KEY": load_tmdb_key(local_root),
        "DATA_DIR": str(local_root / "data"),
        "ML_ARTIFACTS_DIR": str(local_root / "ml" / "artifacts"),
    }
    os.environ.update(values)
    os.chdir(resources)


def initialize_database() -> None:
    from app.core.config import get_settings
    from app.db import models  # noqa: F401
    from app.db.base import Base
    from sqlalchemy import create_engine

    Base.metadata.create_all(create_engine(get_settings().database_url))


def wait_for_server(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as connection:
            connection.settimeout(0.25)
            if connection.connect_ex((HOST, PORT)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("Movie Compass could not start its local server")


def main() -> None:
    resources = bundled_root()
    local_root = application_data_root()
    prepare_local_storage(resources, local_root)
    configure_environment(resources, local_root)
    initialize_database()

    import uvicorn
    import webview
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=PORT, log_level="info", access_log=False)
    )
    server_thread = threading.Thread(target=server.run, name="movie-compass-server", daemon=True)
    server_thread.start()
    wait_for_server()
    webview.create_window(
        APP_NAME,
        f"http://{HOST}:{PORT}/",
        width=1280,
        height=850,
        min_size=(900, 650),
    )
    try:
        webview.start()
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)


if __name__ == "__main__":
    main()
