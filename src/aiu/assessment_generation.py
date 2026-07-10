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
        assessments.append(_homework_assessment(blueprint, week.week))
        if week.week % 2 == 0:
            assessments.append(_quiz_assessment(blueprint, week.week))

    midpoint = max(1, len(blueprint.week_plan) // 2)
    assessments.extend(
        [
            _midterm_assessment(blueprint, midpoint),
            _final_assessment(blueprint),
            _project_assessment(blueprint),
        ]
    )
    return assessments


def _homework_assessment(blueprint: CourseBlueprint, week_number: int) -> Assessment:
    week = _week_for_number(blueprint, week_number)
    objective = _objective_for_week(blueprint, week_number)
    topics = _topic_phrase(week.topics)
    anchor = _anchor_phrase(week)
    return Assessment(
        assessment_id=f"homework_w{week_number:02d}",
        type=AssessmentType.HOMEWORK,
        objectives=[objective],
        prompt=(
            f"Develop a Week {week_number} learning memo on {week.title}. "
            f"Use {topics} to show how this week's material supports the objective: "
            f"{objective} Include evidence from {anchor}."
        ),
        questions=[
            (
                f"Concept map: connect {_indexed_topic(week.topics, 0)}, "
                f"{_indexed_topic(week.topics, 1)}, and {_indexed_topic(week.topics, 2)} "
                f"to the week objective."
            ),
            (
                f"Application analysis: create a concrete {week.title.lower()} case and "
                "walk through the decisions, assumptions, and expected result."
            ),
            (
                f"Evidence task: use {anchor} to justify at least two claims in your memo."
            ),
            (
                "Reflection: identify one limitation, tradeoff, or failure mode that a "
                f"learner should watch for when applying {week.title.lower()}."
            ),
        ],
        answer_key=(
            f"A complete submission explicitly addresses {week.title}; accurately explains "
            f"{topics}; ties the work to '{objective}'; uses the named lecture or source "
            "anchors as evidence; and states a defensible limitation or tradeoff."
        ),
        rubric=(
            f"40% conceptual accuracy for {week.title}; 25% quality of application and "
            "decision tracing; 20% evidence use from lecture/source anchors; 15% clarity, "
            "organization, and limitation analysis."
        ),
        due_week=week_number,
    )


def _quiz_assessment(blueprint: CourseBlueprint, week_number: int) -> Assessment:
    current = _week_for_number(blueprint, week_number)
    previous = _week_for_number(blueprint, max(1, week_number - 1))
    covered_weeks = _unique_weeks([previous, current])
    objectives = [_objective_for_week(blueprint, week.week) for week in covered_weeks]
    topics = _unique_strings([topic for week in covered_weeks for topic in week.topics])
    anchor = _anchor_phrase(current)
    return Assessment(
        assessment_id=f"quiz_w{week_number:02d}",
        type=AssessmentType.QUIZ,
        objectives=objectives,
        prompt=(
            f"Answer concise quiz questions covering {_week_span_phrase(covered_weeks)}, "
            f"with emphasis on {_topic_phrase(topics)}."
        ),
        questions=[
            (
                f"Define {_indexed_topic(topics, 0)} and explain why it matters for "
                f"{current.title}."
            ),
            (
                f"Distinguish {_indexed_topic(topics, 1)} from {_indexed_topic(topics, 2)} "
                "using one course-specific consequence."
            ),
            (
                f"In a {current.title.lower()} scenario, which diagnostic step would you "
                f"take first when {_indexed_topic(topics, 3)} breaks down, and why?"
            ),
            f"Name one lecture or source anchor from {anchor} and state what it supports.",
        ],
        answer_key=(
            "Correct responses use the course vocabulary precisely, compare the requested "
            f"topics without collapsing them, choose a diagnostic step that fits {current.title}, "
            "and cite a relevant lecture/source anchor."
        ),
        rubric=(
            "Score for precise definitions, accurate distinctions, scenario reasoning, and "
            "specific evidence from the covered weeks."
        ),
        due_week=week_number,
    )


def _midterm_assessment(blueprint: CourseBlueprint, midpoint: int) -> Assessment:
    covered_weeks = [week for week in blueprint.week_plan if week.week <= midpoint]
    topics = _unique_strings([topic for week in covered_weeks for topic in week.topics])
    objectives = blueprint.outcomes[: max(1, min(2, len(blueprint.outcomes)))]
    return Assessment(
        assessment_id="midterm",
        type=AssessmentType.MIDTERM,
        objectives=objectives,
        prompt=(
            f"Write a midterm synthesis for {_week_span_phrase(covered_weeks)} in "
            f"{blueprint.course_title}. Focus on {_topic_phrase(topics, limit=5)}."
        ),
        questions=[
            (
                f"Synthesize how {covered_weeks[0].title} develops into "
                f"{covered_weeks[-1].title}; name the dependency chain between them."
            ),
            (
                f"Analyze an applied problem that requires {_indexed_topic(topics, 0)}, "
                f"{_indexed_topic(topics, 1)}, and {_indexed_topic(topics, 2)}."
            ),
            (
                "Choose two weeks from the covered span and compare their assumptions, "
                "tradeoffs, and evaluation criteria."
            ),
        ],
        answer_key=(
            "High-scoring exams trace relationships across the covered weeks, apply the "
            "named topics to a concrete problem, and evaluate assumptions rather than "
            "listing isolated facts."
        ),
        rubric=(
            "35% cross-week synthesis, 30% applied analysis, 20% tradeoff evaluation, "
            "15% clarity and use of course vocabulary."
        ),
        due_week=midpoint,
    )


def _final_assessment(blueprint: CourseBlueprint) -> Assessment:
    topics = _unique_strings([topic for week in blueprint.week_plan for topic in week.topics])
    module_titles = [module.title for module in blueprint.modules]
    return Assessment(
        assessment_id="final",
        type=AssessmentType.FINAL,
        objectives=blueprint.outcomes,
        prompt=(
            f"Create a final integrative analysis for {blueprint.course_title}. Connect "
            f"{_topic_phrase(module_titles, limit=4)} to the course outcomes and explain how "
            f"{_topic_phrase(topics, limit=6)} transfer beyond the final week."
        ),
        questions=[
            "Build an argument that connects every course outcome to specific weeks or modules.",
            (
                f"Evaluate a course-scale case that requires {_indexed_topic(topics, 0)}, "
                f"{_indexed_topic(topics, 1)}, and {_indexed_topic(topics, 2)}."
            ),
            "Identify the strongest unresolved tradeoff in the course and defend a response.",
            "Explain how you would continue learning or building after the course ends.",
        ],
        answer_key=(
            "Excellent final responses connect all outcomes to concrete course artifacts, "
            "use precise module/week evidence, evaluate a nontrivial tradeoff, and propose "
            "a credible continuation path."
        ),
        rubric=(
            "30% outcome integration, 25% evidence from weeks/modules, 25% case analysis "
            "and tradeoff reasoning, 20% communication and forward plan."
        ),
        due_week=len(blueprint.week_plan),
    )


def _project_assessment(blueprint: CourseBlueprint) -> Assessment:
    final_weeks = blueprint.week_plan[-min(4, len(blueprint.week_plan)) :]
    topics = _unique_strings([topic for week in final_weeks for topic in week.topics])
    return Assessment(
        assessment_id="course_project",
        type=AssessmentType.PROJECT,
        objectives=blueprint.outcomes,
        prompt=(
            f"Build a capstone artifact for {blueprint.course_title} that demonstrates the "
            f"course outcomes through {_topic_phrase(topics, limit=5)}. The artifact may be "
            "a design brief, analysis portfolio, prototype, research dossier, or implementation "
            "package appropriate to the course subject."
        ),
        questions=[
            "Submit a proposal that names the target problem, scope, success criteria, and risks.",
            "Submit the artifact with annotations that map major decisions to course outcomes.",
            "Include an evaluation plan using criteria from the final four weeks of the course.",
            "Submit a reflection explaining what changed between proposal and final artifact.",
        ],
        answer_key=(
            "Successful projects provide a coherent artifact, explicit outcome mapping, "
            "week-specific evaluation criteria, evidence-backed decisions, and a reflection "
            "that names meaningful revisions."
        ),
        rubric=(
            "25% outcome coverage, 25% artifact quality, 20% evaluation method, "
            "15% evidence and decision rationale, 15% reflection and revision quality."
        ),
        due_week=len(blueprint.week_plan),
    )


def _week_for_number(blueprint: CourseBlueprint, week_number: int):
    for week in blueprint.week_plan:
        if week.week == week_number:
            return week
    raise AssessmentGenerationError(f"No week plan found for week {week_number}.")


def _objective_for_week(blueprint: CourseBlueprint, week_number: int) -> str:
    return blueprint.outcomes[(week_number - 1) % len(blueprint.outcomes)]


def _topic_phrase(values: list[str], *, limit: int = 3) -> str:
    selected = [content_snippet(value, max_chars=120) for value in values if value][:limit]
    if not selected:
        return "the stated course topics"
    if len(selected) == 1:
        return selected[0]
    if len(selected) == 2:
        return f"{selected[0]} and {selected[1]}"
    return f"{', '.join(selected[:-1])}, and {selected[-1]}"


def _indexed_topic(values: list[str], index: int) -> str:
    if not values:
        return "the relevant course concept"
    return content_snippet(values[index % len(values)], max_chars=120)


def _anchor_phrase(week) -> str:
    anchors = [content_snippet(anchor, max_chars=140) for anchor in week.source_focus[:2]]
    if not anchors:
        anchors = [content_snippet(title, max_chars=140) for title in week.lecture_titles[:2]]
    return _topic_phrase(anchors, limit=2)


def _week_span_phrase(weeks) -> str:
    if not weeks:
        return "the planned course weeks"
    if len(weeks) == 1:
        return f"Week {weeks[0].week}: {weeks[0].title}"
    title_phrase = _topic_phrase([week.title for week in weeks])
    return f"Weeks {weeks[0].week}-{weeks[-1].week}: {title_phrase}"


def _unique_weeks(weeks) -> list:
    seen: set[int] = set()
    result = []
    for week in weeks:
        if week.week in seen:
            continue
        seen.add(week.week)
        result.append(week)
    return result


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        result.append(normalized)
    return result


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
