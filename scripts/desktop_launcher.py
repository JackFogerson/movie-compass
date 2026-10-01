from __future__ import annotations

import json
import logging
import multiprocessing
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

APP_NAME = "Movie Compass"
HOST = "127.0.0.1"
PREFERRED_PORT = 8765


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


def bundled_tmdb_key(resources: Path) -> str:
    """Read a build-injected shared key without ever placing it in source control."""
    key_path = resources / "data" / "bootstrap" / "tmdb-access.key"
    if not key_path.is_file():
        return ""
    return key_path.read_text(encoding="utf-8").strip()


def load_tmdb_key(resources: Path, local_root: Path) -> str:
    supplied_key = os.environ.get("TMDB_API_KEY", "").strip()
    if supplied_key:
        return supplied_key
    settings_path = local_root / "settings.env"
    if settings_path.is_file():
        for line in settings_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TMDB_API_KEY="):
                saved_key = line.partition("=")[2].strip()
                if saved_key:
                    return saved_key
    shared_key = bundled_tmdb_key(resources)
    if shared_key:
        return shared_key
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        value = simpledialog.askstring(
            APP_NAME,
            "Paste your TMDB API key. It is stored only on this computer.\n\n"
            "You can leave this blank and use the bundled offline catalog, but live title "
            "search, posters, and streaming updates will be limited. Movie Compass will ask "
            "again the next time it starts if no key is saved.",
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
        "TMDB_API_KEY": load_tmdb_key(resources, local_root),
        "DATA_DIR": str(local_root / "data"),
        "ML_ARTIFACTS_DIR": str(local_root / "ml" / "artifacts"),
        # Frozen scientific-library builds can otherwise create dozens of
        # BLAS workers during import and deadlock on some Windows machines.
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    os.environ.update(values)
    os.chdir(resources)


def initialize_database() -> None:
    from app.core.config import get_settings
    from app.db import models  # noqa: F401
    from app.db.base import Base
    from sqlalchemy import create_engine

    Base.metadata.create_all(create_engine(get_settings().database_url))


def select_port() -> int:
    """Prefer the familiar port but recover when another local process owns it."""
    with socket.socket() as probe:
        try:
            probe.bind((HOST, PREFERRED_PORT))
        except OSError:
            probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def wait_for_server(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as connection:
            connection.settimeout(0.25)
            if connection.connect_ex((HOST, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("Movie Compass could not start its local server")


def configure_startup_log(local_root: Path) -> Path:
    log_path = local_root / "logs" / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    return log_path


def show_fatal_error(log_path: Path, error: BaseException) -> None:
    message = (
        "Movie Compass could not start.\n\n"
        f"{type(error).__name__}: {error}\n\n"
        f"A diagnostic log was saved at:\n{log_path}"
    )
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message, parent=root)
        root.destroy()
    except Exception:
        pass


def run_desktop() -> None:
    resources = bundled_root()
    local_root = application_data_root()
    configure_startup_log(local_root)
    logging.info("Starting Movie Compass from %s", resources)
    prepare_local_storage(resources, local_root)
    logging.info("Local catalog and model files are ready")
    configure_environment(resources, local_root)
    logging.info("Desktop environment is configured")
    initialize_database()
    logging.info("Personal database is ready")

    logging.info("Loading the local web server")
    import uvicorn

    logging.info("Loading the Movie Compass application")
    from app.main import app

    logging.info("Movie Compass application loaded")
    port = select_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
            # A --windowed PyInstaller app has no stderr stream. Uvicorn's
            # default color formatter calls stderr.isatty() and otherwise
            # aborts before the server starts. The launcher already writes a
            # persistent file log, so keep Uvicorn on that logging pipeline.
            log_config=None,
        )
    )
    server_thread = threading.Thread(target=server.run, name="movie-compass-server", daemon=True)
    server_thread.start()
    logging.info("Waiting for the local server on port %s", port)
    wait_for_server(port)
    url = f"http://{HOST}:{port}/"
    logging.info("Local server ready at %s", url)
    if os.environ.get("MOVIE_COMPASS_SMOKE_TEST") == "1":
        with urllib.request.urlopen(f"{url}health", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"Desktop health check returned HTTP {response.status}")
            health = json.loads(response.read().decode("utf-8"))
            if health.get("tmdb") != "configured":
                raise RuntimeError("Packaged desktop app does not have a TMDB connection")
        logging.info("Packaged desktop smoke test passed")
        server.should_exit = True
        server_thread.join(timeout=10)
        return
    try:
        # Use the bundled Qt browser directly. There is deliberately no
        # external-browser or operating-system webview fallback here.
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication

        qt_app = QApplication.instance() or QApplication(sys.argv)
        window = QWebEngineView()
        window.setWindowTitle(APP_NAME)
        window.resize(1280, 850)
        window.setMinimumSize(900, 650)
        load_error: list[str] = []

        def application_loaded(succeeded: bool) -> None:
            if not succeeded:
                load_error.append("Bundled desktop window could not load Movie Compass")
                qt_app.quit()
                return
            if os.environ.get("MOVIE_COMPASS_NATIVE_SMOKE_TEST") == "1":
                logging.info("Bundled Qt desktop window loaded successfully")
                QTimer.singleShot(100, qt_app.quit)

        window.loadFinished.connect(application_loaded)
        window.setUrl(QUrl(url))
        window.show()
        qt_app.exec()
        if load_error:
            raise RuntimeError(load_error[0])
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        logging.info("Movie Compass stopped")


def main() -> None:
    local_root = application_data_root()
    log_path = local_root / "logs" / "startup.log"
    try:
        run_desktop()
    except BaseException as error:
        try:
            log_path = configure_startup_log(local_root)
            logging.critical("Movie Compass failed to start\n%s", traceback.format_exc())
        finally:
            show_fatal_error(log_path, error)
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
