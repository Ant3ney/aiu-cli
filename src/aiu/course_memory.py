"""Compact course memory for continuity-aware generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.lecture_quality import transcript_word_count
from aiu.models import Assessment, CourseBlueprint, LabSession, LectureSession
from aiu.project import update_manifest_artifacts

COURSE_MEMORY_REF = "course_memory.json"
MAX_RECENT_LECTURES = 4
MAX_RECENT_EVENTS = 6
MAX_AGGREGATE_CONCEPTS = 18


def load_course_memory(course_root: str | Path) -> dict[str, Any]:
    """Load persisted course memory, returning an empty memory document if absent."""

    store = ArtifactStore(course_root)
    if not store.course_path(COURSE_MEMORY_REF).exists():
        return _empty_memory()
    memory = store.read_json(COURSE_MEMORY_REF)
    memory.setdefault("version", 1)
    memory.setdefault("lectures", [])
    memory.setdefault("activities", [])
    memory.setdefault("assessments", [])
    memory.setdefault("covered_concepts", [])
    memory.setdefault("open_threads", [])
    return memory


def write_course_memory(course_root: str | Path, memory: dict[str, Any]) -> None:
    """Persist course memory and index it in the manifest."""

    memory["updated_at"] = _iso_timestamp()
    store = ArtifactStore(course_root)
    store.write_json(COURSE_MEMORY_REF, memory)
    if store.course_path("manifest.json").exists():
        update_manifest_artifacts(
            course_root,
            [("course_memory", "json", COURSE_MEMORY_REF)],
        )


def build_lecture_context_packet(
    course_root: str | Path,
    blueprint: CourseBlueprint,
    item: dict[str, Any],
    objectives: list[str],
    *,
    source_context: str,
) -> dict[str, Any]:
    """Build bounded lecture context from persisted memory and the course plan."""

    week = int(item["week"])
    day = int(item["day"])
    memory = load_course_memory(course_root)
    prior_lectures = [
        lecture
        for lecture in memory.get("lectures", [])
        if _is_before(
            int(lecture.get("week", 0)),
            int(lecture.get("day", 0)),
            week,
            day,
        )
    ]
    prior_activities = [
        activity
        for activity in memory.get("activities", [])
        if int(activity.get("week", 0)) <= week
    ]
    prior_assessments = [
        assessment
        for assessment in memory.get("assessments", [])
        if int(assessment.get("week", 0)) <= week
    ]
    week_plan = _week_plan_for(blueprint, week)
    planned_assessments = _planned_assessment_events(blueprint, week)
    covered_concepts = _unique(
        [
            *memory.get("covered_concepts", []),
            *[
                concept
                for lecture in prior_lectures
                for concept in lecture.get("covered_concepts", [])
            ],
        ]
    )[:MAX_AGGREGATE_CONCEPTS]
    avoid_repeating = _unique(
        [
            concept
            for lecture in prior_lectures[-MAX_RECENT_LECTURES:]
            for concept in lecture.get("avoid_repeating", [])
        ]
    )[:8]
    weave_forward = _unique(
        [
            thread
            for lecture in prior_lectures[-MAX_RECENT_LECTURES:]
            for thread in lecture.get("weave_forward", [])
        ]
    )[:8]
    return {
        "course_title": blueprint.course_title,
        "lecture_id": str(item["id"]),
        "title": str(item["title"]),
        "week": week,
        "day": day,
        "module_position": _module_position(blueprint, week),
        "current_topics": list(week_plan.topics) if week_plan is not None else [str(item["title"])],
        "objectives": objectives,
        "recent_lectures": prior_lectures[-MAX_RECENT_LECTURES:],
        "recent_events": [*prior_activities, *prior_assessments][-MAX_RECENT_EVENTS:],
        "covered_concepts": covered_concepts,
        "avoid_repeating": avoid_repeating,
        "weave_forward": weave_forward,
        "planned_assessments": planned_assessments,
        "source_context": source_context,
        "context_policy": (
            "Advance from prior summaries, briefly recall earlier ideas only when needed, "
            "and do not re-teach concepts already marked as extensively covered."
        ),
    }


def lecture_context_prompt(packet: dict[str, Any]) -> str:
    """Render a compact context packet for provider prompts."""

    recent_lectures = _lines(
        lecture.get("summary", "")
        for lecture in packet.get("recent_lectures", [])
        if lecture.get("summary")
    )
    recent_events = _lines(
        event.get("summary", "")
        for event in packet.get("recent_events", [])
        if event.get("summary")
    )
    return "\n".join(
        [
            "Lecture continuity packet:",
            f"- Module position: {packet.get('module_position', 'Not specified')}",
            f"- Current topics: {_join(packet.get('current_topics', []))}",
            f"- Already covered: {_join(packet.get('covered_concepts', []))}",
            f"- Avoid re-teaching: {_join(packet.get('avoid_repeating', []))}",
            f"- Weave forward briefly: {_join(packet.get('weave_forward', []))}",
            f"- Recent lecture summaries: {recent_lectures}",
            f"- Recent lab/assessment events: {recent_events}",
            f"- Planned assessment milestones: {_join(packet.get('planned_assessments', []))}",
            f"- Policy: {packet.get('context_policy', '')}",
        ]
    )


def record_lecture_memory(
    course_root: str | Path,
    lecture: LectureSession,
    blueprint: CourseBlueprint,
    *,
    artifact_ref: str,
) -> None:
    """Record a compact memory entry for one generated lecture."""

    memory = load_course_memory(course_root)
    week_plan = _week_plan_for(blueprint, lecture.week)
    topics = list(week_plan.topics) if week_plan is not None else [lecture.title]
    covered_concepts = _unique([*topics, *lecture.objectives])
    entry = {
        "artifact_ref": artifact_ref,
        "avoid_repeating": covered_concepts[:5],
        "covered_concepts": covered_concepts,
        "day": lecture.day,
        "lecture_id": lecture.lecture_id,
        "summary": (
            f"{lecture.title} covered {', '.join(covered_concepts[:4])}. "
            f"Future lectures should build on this instead of re-teaching it."
        ),
        "title": lecture.title,
        "type": "lecture",
        "week": lecture.week,
        "weave_forward": [
            f"Use {concept} as prior foundation."
            for concept in covered_concepts[:3]
        ],
        "word_count": transcript_word_count(lecture.transcript),
    }
    memory["lectures"] = _replace_entry(
        memory.get("lectures", []),
        entry,
        key="lecture_id",
    )
    memory["covered_concepts"] = _unique(
        [*memory.get("covered_concepts", []), *covered_concepts]
    )[:MAX_AGGREGATE_CONCEPTS]
    memory["open_threads"] = _unique(
        [*memory.get("open_threads", []), *entry["weave_forward"]]
    )[:MAX_AGGREGATE_CONCEPTS]
    write_course_memory(course_root, memory)


def record_lab_memory(
    course_root: str | Path,
    lab: LabSession,
    *,
    artifact_ref: str,
) -> None:
    """Record a compact memory entry for one lab."""

    memory = load_course_memory(course_root)
    entry = {
        "activity_id": lab.lab_id,
        "artifact_ref": artifact_ref,
        "covered_concepts": list(lab.goals),
        "summary": f"{lab.title} practiced {', '.join(lab.goals[:3])}.",
        "type": "lab",
        "week": lab.week,
    }
    memory["activities"] = _replace_entry(
        memory.get("activities", []),
        entry,
        key="activity_id",
    )
    write_course_memory(course_root, memory)


def record_activity_memory(
    course_root: str | Path,
    activity: dict[str, Any],
    *,
    artifact_ref: str,
) -> None:
    """Record a compact memory entry for a non-lab activity."""

    metadata = activity["metadata"]
    memory = load_course_memory(course_root)
    objectives = list(metadata.get("objectives", []))
    entry = {
        "activity_id": str(metadata["activity_id"]),
        "artifact_ref": artifact_ref,
        "covered_concepts": objectives,
        "summary": f"Week {metadata['week']} seminar activity reinforced {_join(objectives)}.",
        "type": str(metadata.get("type", "activity")),
        "week": int(metadata["week"]),
    }
    memory["activities"] = _replace_entry(
        memory.get("activities", []),
        entry,
        key="activity_id",
    )
    write_course_memory(course_root, memory)


def record_assessment_memory(
    course_root: str | Path,
    assessment: Assessment,
    *,
    artifact_ref: str,
) -> None:
    """Record a compact memory entry for one assessment."""

    memory = load_course_memory(course_root)
    entry = {
        "artifact_ref": artifact_ref,
        "assessment_id": assessment.assessment_id,
        "covered_concepts": list(assessment.objectives),
        "summary": (
            f"{assessment.type.value} {assessment.assessment_id} checked "
            f"{_join(assessment.objectives)}."
        ),
        "type": assessment.type.value,
        "week": assessment.due_week,
    }
    memory["assessments"] = _replace_entry(
        memory.get("assessments", []),
        entry,
        key="assessment_id",
    )
    write_course_memory(course_root, memory)


def _empty_memory() -> dict[str, Any]:
    now = _iso_timestamp()
    return {
        "activities": [],
        "assessments": [],
        "covered_concepts": [],
        "created_at": now,
        "lectures": [],
        "open_threads": [],
        "updated_at": now,
        "version": 1,
    }


def _replace_entry(
    entries: list[dict[str, Any]],
    entry: dict[str, Any],
    *,
    key: str,
) -> list[dict[str, Any]]:
    kept = [existing for existing in entries if existing.get(key) != entry.get(key)]
    return sorted(
        [*kept, entry],
        key=lambda value: (int(value.get("week", 0)), str(value.get(key))),
    )


def _is_before(entry_week: int, entry_day: int, week: int, day: int) -> bool:
    return (entry_week, entry_day) < (week, day)


def _week_plan_for(blueprint: CourseBlueprint, week: int) -> Any | None:
    for week_plan in blueprint.week_plan:
        if week_plan.week == week:
            return week_plan
    return None


def _module_position(blueprint: CourseBlueprint, week: int) -> str:
    for module in blueprint.modules:
        if week in module.weeks:
            return f"{module.title}, week {week} of weeks {min(module.weeks)}-{max(module.weeks)}"
    return f"Week {week} of {len(blueprint.week_plan)}"


def _planned_assessment_events(blueprint: CourseBlueprint, week: int) -> list[str]:
    events: list[str] = []
    for assessment in blueprint.assessment_plan:
        if max(1, week - 1) <= assessment.due_week <= week + 1:
            events.append(
                f"{assessment.assessment_id} ({assessment.type.value}) due week "
                f"{assessment.due_week}: {assessment.description}"
            )
    return events


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        unique_values.append(normalized)
    return unique_values


def _join(values: Any) -> str:
    if not values:
        return "None yet"
    if isinstance(values, str):
        return values
    return "; ".join(str(value) for value in values)


def _lines(values: Any) -> str:
    lines = [str(value) for value in values if str(value).strip()]
    if not lines:
        return "None yet"
    return " | ".join(lines)


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
