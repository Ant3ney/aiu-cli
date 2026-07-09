"""Deterministic runtime rails for generated AI University courses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from aiu.artifact_store import ArtifactStore
from aiu.config import LabPolicy
from aiu.lecture_quality import minimum_transcript_words, transcript_word_count
from aiu.logging import ProgressCallback, emit_progress
from aiu.models import Assessment, CourseBlueprint, CourseManifest, LabSession, LectureSession
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, fail_stage, start_stage

RAILS_REF = "rails.json"
RAILS_SCHEMA_NAME = "aiu.course_rails"
RAILS_SCHEMA_VERSION = 1


class CourseRailsError(ValueError):
    """Raised when course runtime rails cannot be generated."""


def generate_course_rails(
    course_root: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Write the deterministic rails file used by non-AI course runtimes."""

    start_stage(course_root, "rails")
    store = ArtifactStore(course_root)
    try:
        rails = build_course_rails(course_root)
        store.write_json(RAILS_REF, rails)
        update_manifest_artifacts(
            course_root,
            [
                (
                    "course_rails",
                    "json",
                    RAILS_REF,
                    {
                        "schema": RAILS_SCHEMA_NAME,
                        "schema_version": RAILS_SCHEMA_VERSION,
                    },
                )
            ],
        )
        complete_stage(course_root, "rails", [RAILS_REF])
        emit_progress(
            progress,
            "rails",
            "Created deterministic course rails",
            artifact=RAILS_REF,
            detail=(
                f"{len(rails['weeks'])} week(s), "
                f"{len(rails['day_by_day_plan'])} teaching session(s)"
            ),
        )
        return [RAILS_REF]
    except CourseRailsError as exc:
        fail_stage(course_root, "rails", str(exc))
        raise
    except (OSError, ValueError, PydanticValidationError, KeyError) as exc:
        message = f"Unable to generate {RAILS_REF}: {exc}"
        fail_stage(course_root, "rails", message)
        raise CourseRailsError(message) from exc


def build_course_rails(course_root: str | Path) -> dict[str, Any]:
    """Build a deterministic, path-based runtime plan for a generated course."""

    store = ArtifactStore(course_root)
    manifest = CourseManifest.model_validate(_read_required_json(store, "manifest.json"))
    blueprint = CourseBlueprint.model_validate(
        _read_required_json(store, "approved_course_blueprint.json")
    )
    schedule = _read_required_json(store, "schedule.json")

    lectures = _lecture_catalog(store, schedule)
    activities = _activity_catalog(store, blueprint, schedule)
    assessments = _assessment_catalog(store)
    week_entries = _week_entries(blueprint, lectures, activities, assessments)
    day_plan = _day_by_day_plan(blueprint, lectures, activities, assessments)

    if not lectures:
        raise CourseRailsError("Cannot generate rails before lecture artifacts exist.")
    if not assessments:
        raise CourseRailsError("Cannot generate rails before assessment artifacts exist.")

    return {
        "artifact_catalog": {
            "activities": activities,
            "assessments": assessments,
            "course_materials": _course_materials(store),
            "lectures": lectures,
        },
        "course": {
            "course_id": manifest.course_id,
            "description": blueprint.description,
            "outcomes": blueprint.outcomes,
            "prerequisites": blueprint.prerequisites,
            "refs": {
                "approved_blueprint": "approved_course_blueprint.json",
                "blueprint": "course_blueprint.json",
                "manifest": "manifest.json",
                "schedule": "schedule.json",
            },
            "settings": manifest.settings.model_dump(mode="json"),
            "target_learner": blueprint.target_learner,
            "title": blueprint.course_title,
        },
        "day_by_day_plan": day_plan,
        "presentation_hooks": {
            "activity_completed": "activity:complete",
            "assessment_completed": "assessment:complete",
            "course_completed": "course:complete",
            "course_started": "course:start",
            "lecture_completed": "lecture:complete",
            "session_started": "session:start",
        },
        "runtime_contract": {
            "deterministic_reader": True,
            "path_policy": "All artifact references are relative to the course root.",
            "reader_algorithm": [
                "Load rails.json.",
                "Render course metadata and outcomes from course.",
                "Iterate day_by_day_plan in sequence order.",
                "For each presentation action, load only the referenced artifact path.",
                "Read lecture transcript text from the indicated JSON pointer or Markdown file.",
                "Advance local progress using presentation_hooks; no model call is required.",
            ],
            "transcript_policy": (
                "Rails indexes transcript locations and presentation order; lecture text remains "
                "in lecture JSON and Markdown artifacts."
            ),
        },
        "schema": {
            "name": RAILS_SCHEMA_NAME,
            "version": RAILS_SCHEMA_VERSION,
        },
        "weeks": week_entries,
    }


def _read_required_json(store: ArtifactStore, relative_path: str) -> dict[str, Any]:
    path = store.course_path(relative_path)
    if not path.exists():
        raise CourseRailsError(f"Required rails input is missing: {relative_path}")
    return store.read_json(relative_path)


def _course_materials(store: ArtifactStore) -> list[dict[str, str]]:
    materials = [
        ("syllabus", "syllabus/syllabus.md"),
        ("grading_policy", "syllabus/grading_policy.md"),
        ("reading_list", "syllabus/reading_list.md"),
        ("course_overview", "study_guides/course_overview.md"),
        ("context_research", "context_research.md"),
        ("source_manifest", "source_manifest.json"),
    ]
    return [
        {"id": artifact_id, "path": path}
        for artifact_id, path in materials
        if store.course_path(path).exists()
    ]


def _lecture_catalog(store: ArtifactStore, schedule: dict[str, Any]) -> list[dict[str, Any]]:
    lectures: list[dict[str, Any]] = []
    for item in schedule.get("items", []):
        if item.get("type") != "lecture":
            continue
        lecture_id = str(item["id"])
        week = int(item["week"])
        day = int(item["day"])
        markdown_ref = f"lectures/week_{week:02d}/day_{day:02d}.md"
        json_ref = f"lectures/week_{week:02d}/day_{day:02d}.json"
        cue_ref = f"vr_handoff/lecture_scene_cues/{lecture_id}.json"
        _require_file(store, markdown_ref)
        _require_file(store, json_ref)
        _require_file(store, cue_ref)
        lecture = LectureSession.model_validate(store.read_json(json_ref))
        duration_hours = float(item.get("duration_hours", lecture.estimated_duration))
        lectures.append(
            {
                "cue_ref": cue_ref,
                "day": lecture.day,
                "estimated_duration_hours": lecture.estimated_duration,
                "id": lecture.lecture_id,
                "json_ref": json_ref,
                "markdown_ref": markdown_ref,
                "minimum_transcript_words": minimum_transcript_words(duration_hours),
                "objectives": lecture.objectives,
                "source_refs": lecture.source_refs,
                "title": lecture.title,
                "transcript_json_pointer": "/transcript",
                "transcript_word_count": transcript_word_count(lecture.transcript),
                "week": lecture.week,
            }
        )
    return lectures


def _activity_catalog(
    store: ArtifactStore,
    blueprint: CourseBlueprint,
    schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    scheduled_type_by_week = {
        int(item["week"]): str(item.get("type", "activity"))
        for item in schedule.get("items", [])
        if item.get("type") in {"activity", "lab"} and item.get("week") is not None
    }
    activities: list[dict[str, Any]] = []
    for week_plan in blueprint.week_plan:
        week = week_plan.week
        scheduled_type = scheduled_type_by_week.get(week, "activity")
        if blueprint.lab_policy == LabPolicy.NEVER:
            activity_id = f"activity_w{week:02d}"
            markdown_ref = f"artifacts/activities/week_{week:02d}_activity.md"
            json_ref = f"artifacts/activities/week_{week:02d}_activity.json"
            _require_file(store, markdown_ref)
            _require_file(store, json_ref)
            metadata = store.read_json(json_ref)
            activities.append(
                {
                    "concrete_type": "activity",
                    "id": activity_id,
                    "json_ref": json_ref,
                    "markdown_ref": markdown_ref,
                    "objectives": list(metadata.get("objectives", [])),
                    "scheduled_type": scheduled_type,
                    "title": f"Week {week} Seminar Activity",
                    "week": week,
                }
            )
            continue

        lab_id = f"lab_w{week:02d}"
        markdown_ref = f"labs/week_{week:02d}_lab.md"
        json_ref = f"labs/week_{week:02d}_lab.json"
        cue_ref = f"vr_handoff/lab_scene_cues/{lab_id}.json"
        _require_file(store, markdown_ref)
        _require_file(store, json_ref)
        _require_file(store, cue_ref)
        lab = LabSession.model_validate(store.read_json(json_ref))
        activities.append(
            {
                "concrete_type": "lab",
                "cue_ref": cue_ref,
                "id": lab.lab_id,
                "json_ref": json_ref,
                "markdown_ref": markdown_ref,
                "objectives": lab.goals,
                "scheduled_type": scheduled_type,
                "title": lab.title,
                "week": lab.week,
            }
        )
    return activities


def _assessment_catalog(store: ArtifactStore) -> list[dict[str, Any]]:
    assessment_paths = [
        *sorted((store.root / "homework").glob("*.json")),
        *sorted((store.root / "quizzes").glob("*.json")),
        *sorted((store.root / "exams").glob("*.json")),
        *sorted((store.root / "projects").glob("*.json")),
    ]
    assessments: list[dict[str, Any]] = []
    for path in assessment_paths:
        json_ref = path.relative_to(store.root).as_posix()
        assessment = Assessment.model_validate(store.read_json(json_ref))
        markdown_ref = json_ref.removesuffix(".json") + ".md"
        rubric_ref = f"rubrics/{assessment.assessment_id}.md"
        answer_key_ref = f"answer_keys/{assessment.assessment_id}.md"
        _require_file(store, markdown_ref)
        _require_file(store, rubric_ref)
        _require_file(store, answer_key_ref)
        assessments.append(
            {
                "answer_key_ref": answer_key_ref,
                "due_week": assessment.due_week,
                "id": assessment.assessment_id,
                "json_ref": json_ref,
                "markdown_ref": markdown_ref,
                "objectives": assessment.objectives,
                "question_count": len(assessment.questions),
                "rubric_ref": rubric_ref,
                "title": assessment.assessment_id.replace("_", " ").title(),
                "type": assessment.type.value,
            }
        )
    return sorted(
        assessments,
        key=lambda item: (int(item["due_week"]), str(item["type"]), str(item["id"])),
    )


def _week_entries(
    blueprint: CourseBlueprint,
    lectures: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lectures_by_week = _group_by_week(lectures)
    activities_by_week = _group_by_week(activities)
    assessments_by_week = _group_by_week(assessments, key="due_week")
    weeks: list[dict[str, Any]] = []
    for week in blueprint.week_plan:
        weeks.append(
            {
                "activity_ids": [item["id"] for item in activities_by_week.get(week.week, [])],
                "assessment_ids_due": [
                    item["id"] for item in assessments_by_week.get(week.week, [])
                ],
                "lecture_ids": [item["id"] for item in lectures_by_week.get(week.week, [])],
                "source_focus": week.source_focus,
                "title": week.title,
                "topics": week.topics,
                "week": week.week,
            }
        )
    return weeks


def _day_by_day_plan(
    blueprint: CourseBlueprint,
    lectures: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lectures_by_week = _group_by_week(lectures)
    activities_by_week = _group_by_week(activities)
    assessments_by_week = _group_by_week(assessments, key="due_week")
    plan: list[dict[str, Any]] = []
    sequence = 1

    for week in blueprint.week_plan:
        for lecture in sorted(lectures_by_week.get(week.week, []), key=lambda item: item["day"]):
            plan.append(_lecture_session(sequence, week.week, lecture))
            sequence += 1
        for activity in activities_by_week.get(week.week, []):
            plan.append(_activity_session(sequence, week.week, activity))
            sequence += 1
        due_assessments = assessments_by_week.get(week.week, [])
        if due_assessments:
            plan.append(_assessment_session(sequence, week.week, due_assessments))
            sequence += 1
    return plan


def _lecture_session(sequence: int, week: int, lecture: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_refs": {
            "cue_ref": lecture["cue_ref"],
            "json_ref": lecture["json_ref"],
            "markdown_ref": lecture["markdown_ref"],
            "transcript_json_pointer": lecture["transcript_json_pointer"],
        },
        "day": lecture["day"],
        "estimated_duration_hours": lecture["estimated_duration_hours"],
        "id": f"session_{sequence:03d}_{lecture['id']}",
        "learning_objectives": lecture["objectives"],
        "presentation_actions": [
            {
                "artifact_id": lecture["id"],
                "json_ref": lecture["json_ref"],
                "markdown_ref": lecture["markdown_ref"],
                "type": "load_content",
            },
            {
                "items": lecture["objectives"],
                "type": "announce_objectives",
            },
            {
                "json_pointer": lecture["transcript_json_pointer"],
                "json_ref": lecture["json_ref"],
                "markdown_ref": lecture["markdown_ref"],
                "minimum_word_count": lecture["minimum_transcript_words"],
                "type": "present_transcript",
            },
            {
                "cue_ref": lecture["cue_ref"],
                "type": "present_scene_cues",
            },
            {
                "completion_hook": f"lecture:complete:{lecture['id']}",
                "type": "checkpoint_progress",
            },
        ],
        "sequence": sequence,
        "session_type": "lecture",
        "title": lecture["title"],
        "week": week,
    }


def _activity_session(sequence: int, week: int, activity: dict[str, Any]) -> dict[str, Any]:
    actions = [
        {
            "artifact_id": activity["id"],
            "json_ref": activity["json_ref"],
            "markdown_ref": activity["markdown_ref"],
            "type": "load_content",
        },
        {
            "items": activity["objectives"],
            "type": "announce_objectives",
        },
    ]
    if activity["concrete_type"] == "lab":
        actions.append(
            {
                "json_pointer": "/steps",
                "json_ref": activity["json_ref"],
                "markdown_ref": activity["markdown_ref"],
                "type": "present_lab_steps",
            }
        )
        actions.append({"cue_ref": activity["cue_ref"], "type": "present_scene_cues"})
    else:
        actions.append(
            {
                "json_ref": activity["json_ref"],
                "markdown_ref": activity["markdown_ref"],
                "type": "present_activity",
            }
        )
    actions.append(
        {
            "completion_hook": f"activity:complete:{activity['id']}",
            "type": "checkpoint_progress",
        }
    )
    content_refs = {
        "json_ref": activity["json_ref"],
        "markdown_ref": activity["markdown_ref"],
    }
    if "cue_ref" in activity:
        content_refs["cue_ref"] = activity["cue_ref"]
    return {
        "content_refs": content_refs,
        "day": None,
        "id": f"session_{sequence:03d}_{activity['id']}",
        "learning_objectives": activity["objectives"],
        "presentation_actions": actions,
        "scheduled_type": activity["scheduled_type"],
        "sequence": sequence,
        "session_type": activity["concrete_type"],
        "title": activity["title"],
        "week": week,
    }


def _assessment_session(
    sequence: int,
    week: int,
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    refs = [
        {
            "answer_key_ref": item["answer_key_ref"],
            "assessment_id": item["id"],
            "json_ref": item["json_ref"],
            "markdown_ref": item["markdown_ref"],
            "rubric_ref": item["rubric_ref"],
            "type": item["type"],
        }
        for item in assessments
    ]
    objectives = _unique(
        [objective for item in assessments for objective in item.get("objectives", [])]
    )
    return {
        "assessment_ids": [item["id"] for item in assessments],
        "content_refs": {"assessments": refs},
        "day": None,
        "id": f"session_{sequence:03d}_week_{week:02d}_assessments_due",
        "learning_objectives": objectives,
        "presentation_actions": [
            {
                "assessment_refs": refs,
                "type": "assign_or_collect_assessments",
            },
            {
                "completion_hook": f"assessment:due:week_{week:02d}",
                "type": "checkpoint_progress",
            },
        ],
        "sequence": sequence,
        "session_type": "assessment_due",
        "title": f"Week {week} Assessments Due",
        "week": week,
    }


def _group_by_week(
    items: list[dict[str, Any]],
    *,
    key: str = "week",
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(int(item[key]), []).append(item)
    return grouped


def _require_file(store: ArtifactStore, relative_path: str) -> None:
    if not store.course_path(relative_path).is_file():
        raise CourseRailsError(f"Required rails artifact is missing: {relative_path}")


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        result.append(normalized)
    return result
