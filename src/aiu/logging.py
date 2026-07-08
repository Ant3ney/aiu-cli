"""Logging helpers for CLI and engine modules."""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*['\"]?[^'\"\s]+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9_.-]*secret[A-Za-z0-9_.-]*\b", flags=re.IGNORECASE),
)


@dataclass(frozen=True)
class ProgressEvent:
    """A human-facing progress update emitted by long-running course jobs."""

    stage: str
    message: str
    artifact: str | None = None
    current: int | None = None
    detail: str | None = None
    snippet: str | None = None
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]


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


class CourseLoadingView:
    """Line-oriented progress view that mirrors updates to the project log."""

    def __init__(self, course_root: str | Path, *, stream: TextIO | None = None) -> None:
        self.course_root = Path(course_root)
        self.stream = stream or sys.stdout
        self.started_at = time.monotonic()
        self.event_count = 0
        self._next_tip_at = 6

    def start(self, title: str, *, detail: str | None = None) -> None:
        """Render the loading view header and record it in the project log."""

        self._write("")
        self._write(title)
        self._write(f"Log: {self.course_root / 'logs' / 'aiu.log'}")
        if detail:
            self._write(f"Scope: {detail}")
        log_project_event(self.course_root, f"course loading view started: {title}")

    def finish(self, message: str) -> None:
        """Render completion for a long-running course job."""

        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        line = f"[{elapsed}] complete  {message}"
        self._write(line)
        log_project_event(self.course_root, f"course loading view completed: {message}")

    def fail(self, message: str) -> None:
        """Render failure for a long-running course job."""

        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        line = f"[{elapsed}] failed    {message}"
        self._write(line)
        log_project_event(self.course_root, f"course loading view failed: {message}")

    def __call__(self, event: ProgressEvent) -> None:
        """Render and persist one progress event."""

        self.event_count += 1
        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        progress = ""
        if event.current is not None and event.total is not None:
            progress = f" ({event.current}/{event.total})"
        elif event.current is not None:
            progress = f" ({event.current})"

        artifact = f" -> {event.artifact}" if event.artifact else ""
        stage = event.stage[:10].ljust(10)
        line = f"[{elapsed}] {stage} {event.message}{progress}{artifact}"
        self._write(line)
        log_project_event(self.course_root, _event_log_line(event))

        if event.detail:
            self._write(f"           {content_snippet(event.detail, max_chars=180)}")
        if event.snippet:
            self._write(f"           preview: {event.snippet}")

        if self.event_count >= self._next_tip_at:
            tip = _tip_for(self.event_count)
            self._write(f"           while you wait: {tip}")
            log_project_event(self.course_root, f"while you wait: {tip}")
            self._next_tip_at += 9

    def _write(self, line: str) -> None:
        print(line, file=self.stream, flush=True)


def emit_progress(
    progress: ProgressCallback | None,
    stage: str,
    message: str,
    *,
    artifact: str | None = None,
    current: int | None = None,
    detail: str | None = None,
    snippet: str | None = None,
    total: int | None = None,
) -> None:
    """Emit a progress event when a caller supplied a progress callback."""

    if progress is None:
        return
    progress(
        ProgressEvent(
            artifact=artifact,
            current=current,
            detail=detail,
            message=message,
            snippet=snippet,
            stage=stage,
            total=total,
        )
    )


def content_snippet(text: str, *, max_chars: int = 220) -> str:
    """Return a compact, redacted one-line preview for progress logs."""

    compact = " ".join(str(text).split())
    for pattern in _SECRET_PATTERNS:
        compact = pattern.sub("[redacted]", compact)
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max(0, max_chars - 3)].rstrip()}..."


def _event_log_line(event: ProgressEvent) -> str:
    parts = [f"{event.stage}: {event.message}"]
    if event.current is not None and event.total is not None:
        parts.append(f"progress={event.current}/{event.total}")
    if event.artifact:
        parts.append(f"artifact={event.artifact}")
    if event.detail:
        parts.append(f"detail={content_snippet(event.detail, max_chars=180)}")
    if event.snippet:
        parts.append(f"preview={event.snippet}")
    return " | ".join(parts)


def _elapsed_label(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _tip_for(event_count: int) -> str:
    tips = [
        "course artifacts are checkpointed as they finish, so reruns can reuse completed stages.",
        "lecture transcripts, JSON metadata, and VR cues are written separately for easier review.",
        "assessment answer keys and rubrics are generated beside learner-facing prompts.",
        "source citations come from extracted chunks when local context files are supplied.",
        "the final validation pass checks completeness before the command exits.",
    ]
    return tips[(event_count // 3) % len(tips)]
