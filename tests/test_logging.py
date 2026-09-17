from __future__ import annotations

import logging
import sys

from app.core.logging import configure_logging


def test_windowed_app_preserves_existing_file_logger(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "desktop.log"
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    handler = logging.FileHandler(log_path, encoding="utf-8")
    try:
        root.handlers = [handler]
        monkeypatch.setattr(sys, "stderr", None)

        configure_logging("INFO")
        logging.info("desktop logging survives")
        handler.flush()

        assert root.handlers == [handler]
        assert "desktop logging survives" in log_path.read_text(encoding="utf-8")
    finally:
        handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)
