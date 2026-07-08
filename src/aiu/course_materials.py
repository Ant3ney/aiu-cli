"""Course-level artifact generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.logging import ProgressCallback, content_snippet, emit_progress
from aiu.models import CourseBlueprint
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, stage_is_complete, start_stage

SYLLABUS_ARTIFACTS = (
    "syllabus/syllabus.md",
    "syllabus/grading_policy.md",
    "syllabus/reading_list.md",
    "study_guides/course_overview.md",
)


class CourseMaterialError(ValueError):
    """Raised when course-level artifacts cannot be generated."""


def generate_syllabus_artifacts(
    course_root: str | Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Generate top-level human-facing course materials."""

    store = ArtifactStore(course_root)
    if not force and stage_is_complete(course_root, "syllabus", SYLLABUS_ARTIFACTS):
        emit_progress(
            progress,
            "syllabus",
            "Reusing completed syllabus stage",
            detail=f"{len(SYLLABUS_ARTIFACTS)} artifact(s) already exist.",
        )
        return list(SYLLABUS_ARTIFACTS)

    approved_path = store.course_path("approved_course_blueprint.json")
    if not approved_path.exists():
        raise CourseMaterialError("Cannot generate syllabus artifacts before blueprint approval.")

    start_stage(course_root, "syllabus")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    source_refs = _source_refs(store)
    emit_progress(
        progress,
        "syllabus",
        "Drafting course-level learner materials",
        detail=f"{blueprint.course_title}; {len(source_refs)} source reference(s)",
    )

    syllabus = _syllabus_markdown(blueprint, source_refs)
    grading_policy = _grading_policy_markdown(blueprint)
    reading_list = _reading_list_markdown(source_refs)
    course_overview = _course_overview_markdown(blueprint)

    _write_markdown_with_progress(
        store,
        "syllabus/syllabus.md",
        syllabus,
        progress=progress,
        message="Created syllabus",
    )
    _write_markdown_with_progress(
        store,
        "syllabus/grading_policy.md",
        grading_policy,
        progress=progress,
        message="Created grading policy",
    )
    _write_markdown_with_progress(
        store,
        "syllabus/reading_list.md",
        reading_list,
        progress=progress,
        message="Created reading list",
    )
    _write_markdown_with_progress(
        store,
        "study_guides/course_overview.md",
        course_overview,
        progress=progress,
        message="Created course overview",
    )
    update_manifest_artifacts(
        course_root,
        [
            ("syllabus", "markdown", "syllabus/syllabus.md"),
            ("grading_policy", "markdown", "syllabus/grading_policy.md"),
            ("reading_list", "markdown", "syllabus/reading_list.md"),
            ("course_overview", "markdown", "study_guides/course_overview.md"),
        ],
    )
    complete_stage(course_root, "syllabus", list(SYLLABUS_ARTIFACTS))
    emit_progress(
        progress,
        "syllabus",
        "Completed syllabus stage",
        detail=f"{len(SYLLABUS_ARTIFACTS)} artifact(s) written.",
    )
    return list(SYLLABUS_ARTIFACTS)


def _write_markdown_with_progress(
    store: ArtifactStore,
    relative_path: str,
    markdown: str,
    *,
    progress: ProgressCallback | None,
    message: str,
) -> None:
    store.write_markdown(relative_path, markdown)
    emit_progress(
        progress,
        "syllabus",
        message,
        artifact=relative_path,
        snippet=content_snippet(markdown),
    )


def _source_refs(store: ArtifactStore) -> list[str]:
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return []
    chunk_manifest: dict[str, Any] = store.read_json("source_index/chunk_manifest.json")
    refs = {
        str(chunk["source_ref"]).split("!", maxsplit=1)[0]
        for chunk in chunk_manifest.get("chunks", [])
        if chunk.get("source_ref")
    }
    return sorted(refs)


def _syllabus_markdown(blueprint: CourseBlueprint, source_refs: list[str]) -> str:
    lines = [
        f"# {blueprint.course_title}",
        "",
        blueprint.description,
        "",
        "## Learning Outcomes",
        *[f"- {outcome}" for outcome in blueprint.outcomes],
        "",
        "## Weekly Structure",
        *[f"- Week {week.week}: {week.title}" for week in blueprint.week_plan],
        "",
        "## Source Grounding",
    ]
    if source_refs:
        lines.extend(f"- {source_ref}" for source_ref in source_refs)
    else:
        lines.append("- No local source chunks were provided for this course.")
    return "\n".join(lines) + "\n"


def _grading_policy_markdown(blueprint: CourseBlueprint) -> str:
    return (
        "\n".join(
            [
                f"# Grading Policy: {blueprint.course_title}",
                "",
                "- Homework: 30%",
                "- Quizzes: 15%",
                "- Labs or activities: 20%",
                "- Midterm: 15%",
                "- Final: 20%",
                "",
                "Assessments map back to the approved course outcomes.",
            ]
        )
        + "\n"
    )


def _reading_list_markdown(source_refs: list[str]) -> str:
    lines = ["# Reading List", ""]
    if source_refs:
        lines.append("## Provided Sources")
        lines.extend(f"- {source_ref}" for source_ref in source_refs)
    else:
        lines.extend(
            [
                "## Provided Sources",
                "- No local readings were supplied.",
                "",
                "## Recommended Study Pattern",
                "- Review each lecture transcript before attempting assignments.",
            ]
        )
    return "\n".join(lines) + "\n"


def _course_overview_markdown(blueprint: CourseBlueprint) -> str:
    lines = [
        f"# Course Overview: {blueprint.course_title}",
        "",
        blueprint.description,
        "",
        "## Modules",
    ]
    for module in blueprint.modules:
        lines.append(f"- {module.title}: weeks {min(module.weeks)}-{max(module.weeks)}")
    lines.extend(["", "## Assessment Strategy"])
    for assessment in blueprint.assessment_plan:
        lines.append(f"- {assessment.assessment_id}: due week {assessment.due_week}")
    return "\n".join(lines) + "\n"
