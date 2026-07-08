"""Logging helpers for CLI and engine modules."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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


def log_project_event(course_root: str | Path, message: str) -> None:
    """Append a simple project-local log event."""

    root = Path(course_root)
    log_path = root / "logs" / "aiu.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} INFO {message}\n")
