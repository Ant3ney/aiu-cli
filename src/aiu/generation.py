"""Course generation orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.approval import approve_course, is_course_approved
from aiu.artifact_store import ArtifactStore
from aiu.assessment_generation import (
    AssessmentGenerationError,
    generate_assessment_artifacts,
)
from aiu.course_materials import CourseMaterialError, generate_syllabus_artifacts
from aiu.lab_generation import LabGenerationError, generate_lab_artifacts
from aiu.lecture_generation import LectureGenerationError, generate_lecture_artifacts
from aiu.regeneration import RegenerationError, regenerate_week_range


class GenerationError(ValueError):
    """Raised when generation cannot proceed."""


def generate_course(
    course_root: str | Path,
    *,
    yes: bool = False,
    dry_run: bool = False,
    stage: str | None = None,
    force: bool = False,
    from_ref: str | None = None,
    to_ref: str | None = None,
) -> dict[str, Any]:
    """Run or simulate course generation after approval."""

    store = ArtifactStore(course_root)
    if not store.course_path("course_blueprint.json").exists():
        raise GenerationError("Cannot generate before course_blueprint.json exists.")

    if yes and not is_course_approved(course_root):
        approve_course(course_root, mode="auto")

    if not is_course_approved(course_root):
        raise GenerationError(
            "Course blueprint must be approved before generation. Run aiu course approve."
        )

    selected_stage = stage or "all"
    if dry_run:
        return {"dry_run": True, "stage": selected_stage, "status": "ready"}

    if from_ref is not None or to_ref is not None:
        if from_ref is None or to_ref is None:
            raise GenerationError("--from and --to must be supplied together.")
        try:
            artifacts = regenerate_week_range(course_root, from_ref, to_ref)
        except RegenerationError as exc:
            raise GenerationError(str(exc)) from exc
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Regenerated lecture range with {len(artifacts)} artifact(s).",
            "stage": "lectures",
            "status": "complete",
        }

    if selected_stage == "syllabus":
        try:
            artifacts = generate_syllabus_artifacts(course_root, force=force)
        except CourseMaterialError as exc:
            raise GenerationError(str(exc)) from exc
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Generated syllabus stage with {len(artifacts)} artifact(s).",
            "stage": selected_stage,
            "status": "complete",
        }

    if selected_stage == "lectures":
        try:
            artifacts = generate_lecture_artifacts(course_root, force=force)
        except LectureGenerationError as exc:
            raise GenerationError(str(exc)) from exc
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Generated lectures stage with {len(artifacts)} artifact(s).",
            "stage": selected_stage,
            "status": "complete",
        }

    if selected_stage == "labs":
        try:
            artifacts = generate_lab_artifacts(course_root, force=force)
        except LabGenerationError as exc:
            raise GenerationError(str(exc)) from exc
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Generated labs stage with {len(artifacts)} artifact(s).",
            "stage": selected_stage,
            "status": "complete",
        }

    if selected_stage == "assessments":
        try:
            artifacts = generate_assessment_artifacts(course_root, force=force)
        except AssessmentGenerationError as exc:
            raise GenerationError(str(exc)) from exc
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Generated assessments stage with {len(artifacts)} artifact(s).",
            "stage": selected_stage,
            "status": "complete",
        }

    if selected_stage == "all":
        artifacts: list[str] = []
        artifacts.extend(generate_syllabus_artifacts(course_root, force=force))
        artifacts.extend(generate_lecture_artifacts(course_root, force=force))
        artifacts.extend(generate_lab_artifacts(course_root, force=force))
        artifacts.extend(generate_assessment_artifacts(course_root, force=force))
        return {
            "artifacts": artifacts,
            "dry_run": False,
            "message": f"Generated all stages with {len(artifacts)} artifact(s).",
            "stage": selected_stage,
            "status": "complete",
        }

    return {
        "dry_run": False,
        "message": "Generation is approved; artifact stages are implemented incrementally.",
        "stage": selected_stage,
        "status": "ready",
    }
