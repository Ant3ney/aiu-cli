"""Learner feedback persistence for course preview refinement."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aiu.artifact_store import ArtifactStore
from aiu.project import update_manifest_artifacts

COURSE_FEEDBACK_REF = "course_feedback.md"


class FeedbackError(ValueError):
    """Raised when course feedback cannot be stored or read."""


def append_course_feedback(
    course_root: str | Path,
    feedback_text: str,
    *,
    created_at: datetime | None = None,
) -> Path:
    """Append learner feedback to the course refinement log."""

    clean_feedback = feedback_text.strip()
    if not clean_feedback:
        raise FeedbackError("Course feedback cannot be empty.")

    store = ArtifactStore(course_root)
    if not store.course_path("manifest.json").exists():
        raise FeedbackError("Cannot add feedback before manifest.json exists.")

    path = store.course_path(COURSE_FEEDBACK_REF)
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
    else:
        existing = "# Course Feedback"

    timestamp = _iso_timestamp(created_at)
    updated = f"{existing}\n\n## Feedback {timestamp}\n\n{clean_feedback}\n"
    store.write_markdown(COURSE_FEEDBACK_REF, updated)
    update_manifest_artifacts(
        course_root,
        [("course_feedback", "markdown", COURSE_FEEDBACK_REF)],
    )
    return path


def read_course_feedback(course_root: str | Path) -> str:
    """Return accumulated course feedback, if any."""

    store = ArtifactStore(course_root)
    path = store.course_path(COURSE_FEEDBACK_REF)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _iso_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
