"""Logging helpers for CLI and engine modules."""

from __future__ import annotations

import logging
import re
import shutil
import sys
import textwrap
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
    """Human-facing progress view that mirrors detailed updates to the project log."""

    def __init__(self, course_root: str | Path, *, stream: TextIO | None = None) -> None:
        self.course_root = Path(course_root)
        self.stream = stream or sys.stdout
        self.started_at = time.monotonic()
        self.event_count = 0
        self._next_tip_at = 6
        self._last_stage: str | None = None

    def start(self, title: str, *, detail: str | None = None) -> None:
        """Render the loading view header and record it in the project log."""

        self._write("")
        self._write(title)
        self._write_wrapped("Project:", str(self.course_root), indent="  ")
        self._write_wrapped("Log:", str(self.course_root / "logs" / "aiu.log"), indent="  ")
        if detail:
            self._write_wrapped("Scope:", detail, indent="  ")
        log_project_event(self.course_root, f"course loading view started: {title}")

    def finish(self, message: str) -> None:
        """Render completion for a long-running course job."""

        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        self._write("")
        self._write_wrapped(f"[{elapsed}] complete", message, indent="  ")
        log_project_event(self.course_root, f"course loading view completed: {message}")

    def fail(self, message: str) -> None:
        """Render failure for a long-running course job."""

        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        self._write("")
        self._write_wrapped(f"[{elapsed}] failed", message, indent="  ")
        log_project_event(self.course_root, f"course loading view failed: {message}")

    def __call__(self, event: ProgressEvent) -> None:
        """Render and persist one progress event."""

        self.event_count += 1
        tip = None
        if self.event_count >= self._next_tip_at:
            tip = _tip_for(self.event_count)
            log_project_event(self.course_root, f"while you wait: {tip}")
            self._next_tip_at += 9
        self._write_line_event(event, tip=tip)
        log_project_event(self.course_root, _event_log_line(event))

    def _write_line_event(self, event: ProgressEvent, *, tip: str | None) -> None:
        if event.stage != self._last_stage:
            self._last_stage = event.stage
            self._write("")
            self._write(f"== {_stage_label(event.stage)} ==")

        elapsed = _elapsed_label(time.monotonic() - self.started_at)
        message = f"{event.message}{_progress_label(event)}"
        self._write_wrapped(f"[{elapsed}]", message, indent="  ")

        if event.artifact:
            self._write_wrapped("artifact:", event.artifact, indent="    ")
        if event.detail:
            detail_chars = max(220, _terminal_width() * 4)
            self._write_wrapped(
                "detail:",
                content_snippet(event.detail, max_chars=detail_chars),
                indent="    ",
            )
        if event.snippet:
            self._write_wrapped("preview:", event.snippet, indent="    ")
        if tip:
            self._write_wrapped("while you wait:", tip, indent="    ")

    def _write_wrapped(self, label: str, text: str, *, indent: str) -> None:
        label = label.strip()
        body = " ".join(str(text).split())
        first_indent = f"{indent}{label} " if label else indent
        later_indent = " " * len(first_indent)
        for line in _wrapped_lines(body, first_indent=first_indent, later_indent=later_indent):
            self._write(line)

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


def _terminal_width() -> int:
    return max(28, shutil.get_terminal_size(fallback=(80, 24)).columns)


def _stage_label(stage: str) -> str:
    return stage.replace("_", " ").replace("-", " ").title()


def _progress_label(event: ProgressEvent) -> str:
    if event.current is None:
        return ""
    if event.total is None:
        return f" ({event.current})"
    current = max(0, event.current)
    total = max(1, event.total)
    if _terminal_width() < 72:
        return f" ({current}/{total})"
    return f" ({current}/{total}) {_progress_bar(current, total)}"


def _progress_bar(current: int, total: int, *, size: int = 12) -> str:
    ratio = min(1.0, max(0.0, current / max(1, total)))
    filled = round(size * ratio)
    return f"[{'#' * filled}{'-' * (size - filled)}]"


def _wrapped_lines(
    text: str,
    *,
    first_indent: str = "",
    later_indent: str = "",
) -> list[str]:
    width = _terminal_width()
    lines = textwrap.wrap(
        text,
        width=width,
        initial_indent=first_indent,
        subsequent_indent=later_indent,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return lines or [first_indent.rstrip()]


def _tip_for(event_count: int) -> str:
    tips = [
        "course artifacts are checkpointed as they finish, so reruns can reuse completed stages.",
        "lecture transcripts, JSON metadata, and VR cues are written separately for easier review.",
        "assessment answer keys and rubrics are generated beside learner-facing prompts.",
        "source citations come from extracted chunks when local context files are supplied.",
        "the final validation pass checks completeness before the command exits.",
    ]
    return tips[(event_count // 3) % len(tips)]
