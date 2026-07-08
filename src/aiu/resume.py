"""Resume interrupted course creation runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.approval import ApprovalError, approve_course, is_course_approved
from aiu.artifact_store import ArtifactStore
from aiu.generation import GenerationError, generate_course
from aiu.logging import ProgressCallback, emit_progress
from aiu.planning import PlanningError, plan_course
from aiu.validation import CourseValidationError, validate_course


class ResumeError(ValueError):
    """Raised when an interrupted course cannot be resumed."""


def resume_course(
    course_root: str | Path,
    *,
    yes: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Resume a course creation pipeline from durable project artifacts."""

    store = ArtifactStore(course_root)
    if not store.course_path("manifest.json").exists():
        raise ResumeError("Cannot resume because manifest.json is missing.")
    if not store.course_path("prompt.md").exists():
        raise ResumeError("Cannot resume because prompt.md is missing.")

    emit_progress(
        progress,
        "resume",
        "Inspecting checkpointed course project",
        detail=str(Path(course_root)),
    )
    try:
        blueprint = plan_course(course_root, progress=progress)
    except PlanningError as exc:
        raise ResumeError(str(exc)) from exc

    approved_now = is_course_approved(course_root)
    if not approved_now:
        if not yes:
            raise ResumeError(
                "Course blueprint is ready but not approved. "
                "Run `aiu course approve <course>` or resume with --yes."
            )
        try:
            approve_course(course_root, mode="auto")
        except ApprovalError as exc:
            raise ResumeError(str(exc)) from exc
        emit_progress(
            progress,
            "approval",
            "Approved blueprint during resume",
            artifact="approved_course_blueprint.json",
            detail="Automatic approval requested with --yes.",
        )

    try:
        generation = generate_course(course_root, progress=progress)
    except GenerationError as exc:
        raise ResumeError(str(exc)) from exc

    emit_progress(
        progress,
        "validation",
        "Running validation after resume",
        artifact="validation_report.json",
    )
    try:
        report = validate_course(course_root)
    except CourseValidationError as exc:
        raise ResumeError(str(exc)) from exc
    emit_progress(
        progress,
        "validation",
        "Resume validation complete",
        artifact="validation_report.json",
        detail=f"status={report.status.value}; {len(report.checks)} check(s)",
    )
    return {
        "blueprint": blueprint.course_title,
        "generation": generation,
        "status": report.status.value,
    }
