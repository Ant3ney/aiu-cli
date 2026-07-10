"""Lab and lab-alternative artifact generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.config import LabPolicy
from aiu.course_memory import record_activity_memory, record_lab_memory
from aiu.logging import ProgressCallback, content_snippet, emit_progress
from aiu.models import CourseBlueprint, LabSession, VRHandoffCue
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, record_artifact_complete, stage_is_complete, start_stage


class LabGenerationError(ValueError):
    """Raised when lab artifacts cannot be generated."""


def generate_lab_artifacts(
    course_root: str | Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Generate labs or documented lab alternatives for each week."""

    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise LabGenerationError("Cannot generate labs before blueprint approval.")

    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    artifacts = _expected_artifacts(blueprint)
    if not force and stage_is_complete(course_root, "labs", artifacts):
        emit_progress(
            progress,
            "labs",
            "Reusing completed labs stage",
            detail=f"{len(artifacts)} lab/activity artifact(s) already exist.",
        )
        return artifacts

    start_stage(course_root, "labs")
    emit_progress(
        progress,
        "labs",
        "Generating weekly labs or applied activities",
        detail=(
            f"{len(blueprint.week_plan)} week(s); policy "
            f"{blueprint.lab_policy.value}"
        ),
    )

    written = _write_lab_weeks(
        course_root,
        blueprint,
        [week.week for week in blueprint.week_plan],
        force=force,
        progress=progress,
    )
    complete_stage(course_root, "labs", written)
    emit_progress(
        progress,
        "labs",
        "Completed labs stage",
        detail=f"{len(written)} artifact(s) written.",
    )
    return written


def generate_lab_week(
    course_root: str | Path,
    *,
    week: int,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Generate one week of lab or activity artifacts without completing the stage."""

    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise LabGenerationError("Cannot generate labs before blueprint approval.")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    if not any(week_plan.week == week for week_plan in blueprint.week_plan):
        raise LabGenerationError(f"No lab or activity found for week {week}.")
    start_stage(course_root, "labs")
    return _write_lab_weeks(
        course_root,
        blueprint,
        [week],
        force=force,
        progress=progress,
    )


def expected_lab_artifacts(course_root: str | Path) -> list[str]:
    """Return all expected lab or lab-alternative artifacts for a course."""

    store = ArtifactStore(course_root)
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    return _expected_artifacts(blueprint)


def complete_lab_stage_if_ready(course_root: str | Path) -> list[str]:
    """Mark the labs stage complete when all expected artifacts exist."""

    store = ArtifactStore(course_root)
    artifacts = expected_lab_artifacts(course_root)
    if all(store.course_path(artifact).exists() for artifact in artifacts):
        complete_stage(course_root, "labs", artifacts)
    return artifacts


def _write_lab_weeks(
    course_root: str | Path,
    blueprint: CourseBlueprint,
    weeks: list[int],
    *,
    force: bool,
    progress: ProgressCallback | None,
) -> list[str]:
    store = ArtifactStore(course_root)
    manifest_entries: list[tuple[str, str, str]] = []
    written: list[str] = []
    total = len(weeks)
    if blueprint.lab_policy == LabPolicy.NEVER:
        for index, week in enumerate(weeks, start=1):
            written.extend(
                _write_activity_week(
                    store,
                    blueprint,
                    week,
                    force=force,
                    index=index,
                    manifest_entries=manifest_entries,
                    progress=progress,
                    total=total,
                )
            )
    else:
        for index, week in enumerate(weeks, start=1):
            written.extend(
                _write_lab_week(
                    store,
                    blueprint,
                    week,
                    force=force,
                    index=index,
                    manifest_entries=manifest_entries,
                    progress=progress,
                    total=total,
                )
            )
    update_manifest_artifacts(course_root, manifest_entries)
    return written


def _write_activity_week(
    store: ArtifactStore,
    blueprint: CourseBlueprint,
    week: int,
    *,
    force: bool,
    index: int,
    manifest_entries: list[tuple[str, str, str]],
    progress: ProgressCallback | None,
    total: int,
) -> list[str]:
    markdown_path = f"artifacts/activities/week_{week:02d}_activity.md"
    json_path = f"artifacts/activities/week_{week:02d}_activity.json"
    if not force and all(store.course_path(path).exists() for path in (markdown_path, json_path)):
        activity = {"metadata": store.read_json(json_path)}
        record_activity_memory(store.root, activity, artifact_ref=markdown_path)
        emit_progress(
            progress,
            "labs",
            "Reusing seminar activity",
            artifact=markdown_path,
            current=index,
            total=total,
        )
        return [markdown_path, json_path]

    activity = _alternative_activity(blueprint, week)
    store.write_markdown(markdown_path, activity["markdown"])
    store.write_json(json_path, activity["metadata"])
    record_activity_memory(store.root, activity, artifact_ref=markdown_path)
    for path in (markdown_path, json_path):
        record_artifact_complete(store.root, "labs", path)
    manifest_entries.extend(
        [
            (f"activity_w{week:02d}_markdown", "markdown", markdown_path),
            (f"activity_w{week:02d}_json", "json", json_path),
        ]
    )
    emit_progress(
        progress,
        "labs",
        "Created seminar activity",
        artifact=markdown_path,
        current=index,
        total=total,
        snippet=content_snippet(activity["markdown"]),
    )
    return [markdown_path, json_path]


def _write_lab_week(
    store: ArtifactStore,
    blueprint: CourseBlueprint,
    week: int,
    *,
    force: bool,
    index: int,
    manifest_entries: list[tuple[str, str, str]],
    progress: ProgressCallback | None,
    total: int,
) -> list[str]:
    lab = _lab_session(blueprint, week)
    markdown_path = f"labs/week_{week:02d}_lab.md"
    json_path = f"labs/week_{week:02d}_lab.json"
    cue_path = f"vr_handoff/lab_scene_cues/{lab.lab_id}.json"
    if not force and all(
        store.course_path(path).exists() for path in (markdown_path, json_path, cue_path)
    ):
        existing_lab = LabSession.model_validate(store.read_json(json_path))
        record_lab_memory(store.root, existing_lab, artifact_ref=markdown_path)
        emit_progress(
            progress,
            "labs",
            "Reusing weekly lab",
            artifact=markdown_path,
            current=index,
            total=total,
            detail=f"{json_path}; {cue_path}",
        )
        return [markdown_path, json_path, cue_path]

    markdown = _lab_markdown(lab, blueprint)
    store.write_markdown(markdown_path, markdown)
    store.write_json(json_path, lab)
    store.write_json(cue_path, {"cues": lab.vr_cues, "lab_id": lab.lab_id})
    record_lab_memory(store.root, lab, artifact_ref=markdown_path)
    for path in (markdown_path, json_path, cue_path):
        record_artifact_complete(store.root, "labs", path)
    manifest_entries.extend(
        [
            (f"{lab.lab_id}_markdown", "markdown", markdown_path),
            (f"{lab.lab_id}_json", "json", json_path),
            (f"{lab.lab_id}_vr_cues", "json", cue_path),
        ]
    )
    emit_progress(
        progress,
        "labs",
        "Created weekly lab",
        artifact=markdown_path,
        current=index,
        total=total,
        detail=f"{json_path}; {cue_path}",
        snippet=content_snippet(markdown),
    )
    return [markdown_path, json_path, cue_path]


def _expected_artifacts(blueprint: CourseBlueprint) -> list[str]:
    artifacts: list[str] = []
    if blueprint.lab_policy == LabPolicy.NEVER:
        for week in blueprint.week_plan:
            artifacts.extend(
                [
                    f"artifacts/activities/week_{week.week:02d}_activity.md",
                    f"artifacts/activities/week_{week.week:02d}_activity.json",
                ]
            )
    else:
        for week in blueprint.week_plan:
            lab_id = f"lab_w{week.week:02d}"
            artifacts.extend(
                [
                    f"labs/week_{week.week:02d}_lab.md",
                    f"labs/week_{week.week:02d}_lab.json",
                    f"vr_handoff/lab_scene_cues/{lab_id}.json",
                ]
            )
    return artifacts


def _lab_session(blueprint: CourseBlueprint, week: int) -> LabSession:
    week_plan = _week_for_number(blueprint, week)
    objective = blueprint.outcomes[(week - 1) % len(blueprint.outcomes)]
    topics = _topic_phrase(week_plan.topics)
    anchor = _anchor_phrase(week_plan)
    lab_id = f"lab_w{week:02d}"
    cue = VRHandoffCue(
        cue_id=f"cue_{lab_id}_setup",
        artifact_id=lab_id,
        timestamp_or_segment="setup",
        scene_type="lab_room",
        professor_action=f"introduce the {week_plan.title} practice task and deliverables",
        visual_aid=f"Week {week}: {week_plan.title}",
        interaction_anchor=f"{lab_id}_setup_check",
    )
    return LabSession(
        lab_id=lab_id,
        week=week,
        title=f"Week {week} Lab: {week_plan.title}",
        goals=[
            objective,
            f"Practice {topics} using the week {week} lecture and source anchors.",
        ],
        setup=(
            f"Review the Week {week} lectures ({'; '.join(week_plan.lecture_titles)}) "
            f"and keep {anchor} available as evidence while working."
        ),
        steps=[
            f"Extract a decision checklist for {week_plan.title} from {topics}.",
            (
                f"Apply the checklist to a concrete {week_plan.title.lower()} case and "
                "record each decision, assumption, and expected result."
            ),
            (
                f"Use {anchor} to verify or challenge at least two decisions in the lab notes."
            ),
            (
                "Write a short reflection naming one tradeoff, edge case, or follow-up "
                f"question raised by {week_plan.title.lower()}."
            ),
        ],
        expected_outputs=[
            f"Decision checklist for {week_plan.title}",
            "Worked case notes with assumptions and expected result",
            "Evidence notes tied to the lecture/source anchors",
            "Reflection on one tradeoff, edge case, or follow-up question",
        ],
        safety_notes=["Use local files responsibly and do not include secrets in submissions."],
        rubric=(
            f"Evaluate the checklist and worked case for accuracy in {week_plan.title}; "
            "evidence quality from the named anchors; clear decision reasoning; and a "
            "specific reflection on limitations or next steps."
        ),
        vr_cues=[cue],
    )


def _lab_markdown(lab: LabSession, blueprint: CourseBlueprint) -> str:
    lines = [
        f"# {lab.title}",
        "",
        f"Lab ID: {lab.lab_id}",
        "",
        f"Policy rationale: {blueprint.lab_policy_rationale}",
        "",
        "## Goals",
        *[f"- {goal}" for goal in lab.goals],
        "",
        "## Setup",
        lab.setup,
        "",
        "## Steps",
        *[f"{index}. {step}" for index, step in enumerate(lab.steps, start=1)],
        "",
        "## Expected Outputs",
        *[f"- {output}" for output in lab.expected_outputs],
        "",
        "## Rubric",
        lab.rubric,
    ]
    return "\n".join(lines) + "\n"


def _alternative_activity(blueprint: CourseBlueprint, week: int) -> dict[str, Any]:
    week_plan = _week_for_number(blueprint, week)
    objective = blueprint.outcomes[(week - 1) % len(blueprint.outcomes)]
    topics = _topic_phrase(week_plan.topics)
    anchor = _anchor_phrase(week_plan)
    activity_id = f"activity_w{week:02d}"
    rationale = blueprint.lab_policy_rationale or "Labs are disabled for this course."
    metadata = {
        "activity_id": activity_id,
        "anchor": anchor,
        "objective": objective,
        "rationale": rationale,
        "title": week_plan.title,
        "topics": week_plan.topics,
        "type": "seminar",
        "week": week,
        "objectives": [objective],
    }
    markdown = (
        "\n".join(
            [
                f"# Week {week} Seminar Activity: {week_plan.title}",
                "",
                f"Activity ID: {activity_id}",
                "",
                f"Rationale: {rationale}",
                "",
                (
                    f"This seminar activity is used instead of a lab and focuses on {topics}."
                ),
                "",
                "## Activity",
                (
                    f"Use {anchor} to debate how {week_plan.title.lower()} supports "
                    f"the objective: {objective}"
                ),
                "",
                "## Deliverables",
                f"- A claim about {week_plan.title} supported by lecture or source evidence.",
                "- One counterargument or limitation.",
                "- A short next-step recommendation for continued study or practice.",
            ]
        )
        + "\n"
    )
    return {"markdown": markdown, "metadata": metadata}


def _week_for_number(blueprint: CourseBlueprint, week_number: int):
    for week in blueprint.week_plan:
        if week.week == week_number:
            return week
    raise LabGenerationError(f"No week plan found for week {week_number}.")


def _topic_phrase(values: list[str], *, limit: int = 3) -> str:
    selected = [content_snippet(value, max_chars=120) for value in values if value][:limit]
    if not selected:
        return "the stated course topics"
    if len(selected) == 1:
        return selected[0]
    if len(selected) == 2:
        return f"{selected[0]} and {selected[1]}"
    return f"{', '.join(selected[:-1])}, and {selected[-1]}"


def _anchor_phrase(week) -> str:
    anchors = [content_snippet(anchor, max_chars=140) for anchor in week.source_focus[:2]]
    if not anchors:
        anchors = [content_snippet(title, max_chars=140) for title in week.lecture_titles[:2]]
    return _topic_phrase(anchors, limit=2)
