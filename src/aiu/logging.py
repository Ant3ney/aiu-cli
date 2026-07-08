"""Logging helpers for CLI and engine modules."""

from __future__ import annotations

import logging
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(verbosity: int = 0, log_file: Path | None = None) -> None:
    """Configure process-wide logging for CLI commands."""

    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT, handlers=handlers, force=True)
