"""Lab and lab-alternative artifact generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.config import LabPolicy
from aiu.models import CourseBlueprint, LabSession, VRHandoffCue
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, record_artifact_complete, stage_is_complete, start_stage


class LabGenerationError(ValueError):
    """Raised when lab artifacts cannot be generated."""


def generate_lab_artifacts(course_root: str | Path, *, force: bool = False) -> list[str]:
    """Generate labs or documented lab alternatives for each week."""

    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise LabGenerationError("Cannot generate labs before blueprint approval.")

    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    artifacts = _expected_artifacts(blueprint)
    if not force and stage_is_complete(course_root, "labs", artifacts):
        return artifacts

    start_stage(course_root, "labs")
    manifest_entries: list[tuple[str, str, str]] = []
    written: list[str] = []

    if blueprint.lab_policy == LabPolicy.NEVER:
        for week in blueprint.week_plan:
            markdown_path = f"artifacts/activities/week_{week.week:02d}_activity.md"
            json_path = f"artifacts/activities/week_{week.week:02d}_activity.json"
            activity = _alternative_activity(blueprint, week.week)
            store.write_markdown(markdown_path, activity["markdown"])
            store.write_json(json_path, activity["metadata"])
            for path in (markdown_path, json_path):
                record_artifact_complete(course_root, "labs", path)
                written.append(path)
            manifest_entries.extend(
                [
                    (f"activity_w{week.week:02d}_markdown", "markdown", markdown_path),
                    (f"activity_w{week.week:02d}_json", "json", json_path),
                ]
            )
    else:
        for week in blueprint.week_plan:
            lab = _lab_session(blueprint, week.week)
            markdown_path = f"labs/week_{week.week:02d}_lab.md"
            json_path = f"labs/week_{week.week:02d}_lab.json"
            cue_path = f"vr_handoff/lab_scene_cues/{lab.lab_id}.json"
            store.write_markdown(markdown_path, _lab_markdown(lab, blueprint))
            store.write_json(json_path, lab)
            store.write_json(cue_path, {"cues": lab.vr_cues, "lab_id": lab.lab_id})
            for path in (markdown_path, json_path, cue_path):
                record_artifact_complete(course_root, "labs", path)
                written.append(path)
            manifest_entries.extend(
                [
                    (f"{lab.lab_id}_markdown", "markdown", markdown_path),
                    (f"{lab.lab_id}_json", "json", json_path),
                    (f"{lab.lab_id}_vr_cues", "json", cue_path),
                ]
            )

    update_manifest_artifacts(course_root, manifest_entries)
    complete_stage(course_root, "labs", written)
    return written


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
    lab_id = f"lab_w{week:02d}"
    cue = VRHandoffCue(
        cue_id=f"cue_{lab_id}_setup",
        artifact_id=lab_id,
        timestamp_or_segment="setup",
        scene_type="lab_room",
        professor_action="introduce the lab setup and expected deliverables",
        visual_aid=f"Week {week} lab bench",
        interaction_anchor=f"{lab_id}_setup_check",
    )
    return LabSession(
        lab_id=lab_id,
        week=week,
        title=f"Week {week} Lab",
        goals=[blueprint.outcomes[(week - 1) % len(blueprint.outcomes)]],
        setup="Prepare the course workspace and review the approved blueprint context.",
        steps=[
            "Review the week objectives.",
            "Complete a guided practice task.",
            "Document observations and submit a short reflection.",
        ],
        expected_outputs=["Completed lab notes", "A short explanation tied to course objectives"],
        safety_notes=["Use local files responsibly and do not include secrets in submissions."],
        rubric=(
            "Complete the required steps, explain decisions clearly, and connect work to outcomes."
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
    activity_id = f"activity_w{week:02d}"
    rationale = blueprint.lab_policy_rationale or "Labs are disabled for this course."
    metadata = {
        "activity_id": activity_id,
        "rationale": rationale,
        "type": "seminar",
        "week": week,
        "objectives": [blueprint.outcomes[(week - 1) % len(blueprint.outcomes)]],
    }
    markdown = (
        "\n".join(
            [
                f"# Week {week} Seminar Activity",
                "",
                f"Activity ID: {activity_id}",
                "",
                f"Rationale: {rationale}",
                "",
                (
                    "Students complete a discussion, case analysis, or workshop activity "
                    "instead of a lab."
                ),
            ]
        )
        + "\n"
    )
    return {"markdown": markdown, "metadata": metadata}
