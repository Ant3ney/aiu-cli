"""Academic assessment artifact generation."""

from __future__ import annotations

from pathlib import Path

from aiu.artifact_store import ArtifactStore
from aiu.course_memory import record_assessment_memory
from aiu.logging import ProgressCallback, content_snippet, emit_progress
from aiu.models import Assessment, AssessmentType, CourseBlueprint
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, record_artifact_complete, stage_is_complete, start_stage


class AssessmentGenerationError(ValueError):
    """Raised when assessment artifacts cannot be generated."""


def generate_assessment_artifacts(
    course_root: str | Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Generate homework, quizzes, exams, project, rubrics, and answer keys."""

    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise AssessmentGenerationError("Cannot generate assessments before blueprint approval.")

    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    assessments = _assessments_for_blueprint(blueprint)
    expected_artifacts = [
        artifact
        for assessment in assessments
        for artifact in _artifact_paths_for_assessment(assessment)
    ]
    if not force and stage_is_complete(course_root, "assessments", expected_artifacts):
        emit_progress(
            progress,
            "assessments",
            "Reusing completed assessments stage",
            detail=f"{len(assessments)} assessment(s), {len(expected_artifacts)} artifact(s).",
        )
        return expected_artifacts

    start_stage(course_root, "assessments")
    emit_progress(
        progress,
        "assessments",
        "Generating homework, quizzes, exams, rubrics, and answer keys",
        detail=f"{len(assessments)} assessment(s) planned.",
    )

    written = _write_assessments(
        course_root,
        assessments,
        force=force,
        progress=progress,
    )
    complete_stage(course_root, "assessments", written)
    emit_progress(
        progress,
        "assessments",
        "Completed assessments stage",
        detail=f"{len(written)} artifact(s) written.",
    )
    return written


def generate_assessment_week(
    course_root: str | Path,
    *,
    week: int,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Generate assessments due in one week without completing the whole stage."""

    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise AssessmentGenerationError("Cannot generate assessments before blueprint approval.")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    assessments = [
        assessment
        for assessment in _assessments_for_blueprint(blueprint)
        if assessment.due_week == week
    ]
    if not assessments:
        return []
    start_stage(course_root, "assessments")
    return _write_assessments(
        course_root,
        assessments,
        force=force,
        progress=progress,
    )


def expected_assessment_artifacts(course_root: str | Path) -> list[str]:
    """Return all expected assessment, rubric, and answer-key artifacts."""

    store = ArtifactStore(course_root)
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    return [
        artifact
        for assessment in _assessments_for_blueprint(blueprint)
        for artifact in _artifact_paths_for_assessment(assessment)
    ]


def complete_assessment_stage_if_ready(course_root: str | Path) -> list[str]:
    """Mark the assessment stage complete when all expected artifacts exist."""

    store = ArtifactStore(course_root)
    artifacts = expected_assessment_artifacts(course_root)
    if all(store.course_path(artifact).exists() for artifact in artifacts):
        complete_stage(course_root, "assessments", artifacts)
    return artifacts


def _write_assessments(
    course_root: str | Path,
    assessments: list[Assessment],
    *,
    force: bool,
    progress: ProgressCallback | None,
) -> list[str]:
    store = ArtifactStore(course_root)
    manifest_entries: list[tuple[str, str, str]] = []
    written: list[str] = []
    for index, assessment in enumerate(assessments, start=1):
        artifacts = _artifact_paths_for_assessment(assessment)
        content_path, json_path, rubric_path, answer_key_path = artifacts
        if not force and all(store.course_path(path).exists() for path in artifacts):
            existing = Assessment.model_validate(store.read_json(json_path))
            record_assessment_memory(course_root, existing, artifact_ref=content_path)
            emit_progress(
                progress,
                "assessments",
                f"Reusing {assessment.type.value} assessment",
                artifact=content_path,
                current=index,
                total=len(assessments),
            )
            written.extend(artifacts)
            continue

        content = _assessment_markdown(assessment)
        rubric = f"# Rubric: {assessment.assessment_id}\n\n{assessment.rubric}\n"
        answer_key = f"# Answer Key: {assessment.assessment_id}\n\n{assessment.answer_key}\n"
        store.write_markdown(content_path, content)
        store.write_json(json_path, assessment)
        store.write_markdown(rubric_path, rubric)
        store.write_markdown(answer_key_path, answer_key)
        record_assessment_memory(course_root, assessment, artifact_ref=content_path)
        for path in artifacts:
            record_artifact_complete(course_root, "assessments", path)
            written.append(path)
        emit_progress(
            progress,
            "assessments",
            f"Created {assessment.type.value} assessment",
            artifact=content_path,
            current=index,
            total=len(assessments),
            detail=f"rubric: {rubric_path}; answer key: {answer_key_path}",
            snippet=content_snippet(content),
        )
        manifest_entries.extend(
            [
                (f"{assessment.assessment_id}_markdown", "markdown", content_path),
                (f"{assessment.assessment_id}_json", "json", json_path),
                (f"{assessment.assessment_id}_rubric", "markdown", rubric_path),
                (f"{assessment.assessment_id}_answer_key", "markdown", answer_key_path),
            ]
        )
    update_manifest_artifacts(course_root, manifest_entries)
    return written


def _assessments_for_blueprint(blueprint: CourseBlueprint) -> list[Assessment]:
    assessments: list[Assessment] = []
    for week in blueprint.week_plan:
        objective = blueprint.outcomes[(week.week - 1) % len(blueprint.outcomes)]
        assessments.append(
            Assessment(
                assessment_id=f"homework_w{week.week:02d}",
                type=AssessmentType.HOMEWORK,
                objectives=[objective],
                prompt=f"Complete a problem set or written response for week {week.week}.",
                questions=[
                    f"Explain the central idea from week {week.week}.",
                    "Apply the idea to a small example.",
                ],
                answer_key=(
                    "A complete answer defines the concept, applies it correctly, "
                    "and notes limitations."
                ),
                rubric=(
                    "Award credit for accuracy, clear reasoning, and connection "
                    "to the learning objective."
                ),
                due_week=week.week,
            )
        )
        if week.week % 2 == 0:
            assessments.append(
                Assessment(
                    assessment_id=f"quiz_w{week.week:02d}",
                    type=AssessmentType.QUIZ,
                    objectives=[objective],
                    prompt=f"Short quiz covering weeks {max(1, week.week - 1)}-{week.week}.",
                    questions=[
                        "Define one key term.",
                        "Choose the best next step for a short scenario.",
                    ],
                    answer_key=(
                        "Correct responses identify the term and justify the scenario choice."
                    ),
                    rubric="Award credit for concise, correct answers tied to course vocabulary.",
                    due_week=week.week,
                )
            )

    midpoint = max(1, len(blueprint.week_plan) // 2)
    assessments.extend(
        [
            Assessment(
                assessment_id="midterm",
                type=AssessmentType.MIDTERM,
                objectives=blueprint.outcomes[:2],
                prompt="Cumulative midterm exam.",
                questions=["Synthesize the first half of the course.", "Solve an applied problem."],
                answer_key=(
                    "Strong answers synthesize foundations and apply methods with justification."
                ),
                rubric="Grade for conceptual accuracy, application quality, and explanation.",
                due_week=midpoint,
            ),
            Assessment(
                assessment_id="final",
                type=AssessmentType.FINAL,
                objectives=blueprint.outcomes,
                prompt="Cumulative final exam.",
                questions=[
                    "Integrate major course outcomes.",
                    "Evaluate tradeoffs in a realistic case.",
                ],
                answer_key="Strong answers integrate outcomes and evaluate tradeoffs clearly.",
                rubric="Grade for synthesis, precision, and defensible reasoning.",
                due_week=len(blueprint.week_plan),
            ),
            Assessment(
                assessment_id="course_project",
                type=AssessmentType.PROJECT,
                objectives=blueprint.outcomes,
                prompt="Complete a capstone project that demonstrates course outcomes.",
                questions=[
                    "Submit the project artifact.",
                    "Submit a reflection mapping work to outcomes.",
                ],
                answer_key="Successful projects demonstrate each outcome with concrete evidence.",
                rubric=(
                    "Grade for completeness, originality, outcome alignment, "
                    "and clear communication."
                ),
                due_week=len(blueprint.week_plan),
            ),
        ]
    )
    return assessments


def _artifact_paths_for_assessment(assessment: Assessment) -> tuple[str, str, str, str]:
    stem = assessment.assessment_id
    directory = {
        AssessmentType.HOMEWORK: "homework",
        AssessmentType.QUIZ: "quizzes",
        AssessmentType.MIDTERM: "exams",
        AssessmentType.FINAL: "exams",
        AssessmentType.PROJECT: "projects",
        AssessmentType.ACTIVITY: "artifacts/activities",
    }[assessment.type]
    content_name = "midterm" if assessment.assessment_id == "midterm" else assessment.assessment_id
    content_name = "final" if assessment.assessment_id == "final" else content_name
    return (
        f"{directory}/{content_name}.md",
        f"{directory}/{content_name}.json",
        f"rubrics/{stem}.md",
        f"answer_keys/{stem}.md",
    )


def _assessment_markdown(assessment: Assessment) -> str:
    lines = [
        f"# {assessment.assessment_id}",
        "",
        f"Type: {assessment.type.value}",
        f"Due week: {assessment.due_week}",
        "",
        "## Objectives",
        *[f"- {objective}" for objective in assessment.objectives],
        "",
        "## Prompt",
        assessment.prompt,
        "",
        "## Questions",
        *[f"{index}. {question}" for index, question in enumerate(assessment.questions, start=1)],
    ]
    return "\n".join(lines) + "\n"
