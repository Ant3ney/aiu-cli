"""Lecture artifact and VR cue generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.models import CourseBlueprint, LectureSession, VRHandoffCue
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, record_artifact_complete, stage_is_complete, start_stage


class LectureGenerationError(ValueError):
    """Raised when lecture artifacts cannot be generated."""


def generate_lecture_artifacts(course_root: str | Path, *, force: bool = False) -> list[str]:
    """Generate scheduled lecture Markdown, JSON, and VR cue artifacts."""

    store = ArtifactStore(course_root)
    schedule_path = store.course_path("schedule.json")
    approved_path = store.course_path("approved_course_blueprint.json")
    if not schedule_path.exists() or not approved_path.exists():
        raise LectureGenerationError("Cannot generate lectures before planning and approval.")

    schedule: dict[str, Any] = store.read_json("schedule.json")
    lecture_items = [item for item in schedule.get("items", []) if item.get("type") == "lecture"]
    artifacts = [artifact for item in lecture_items for artifact in _lecture_artifact_paths(item)]
    if not force and stage_is_complete(course_root, "lectures", artifacts):
        return artifacts

    start_stage(course_root, "lectures")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    source_refs = _source_refs(store)
    manifest_entries: list[tuple[str, str, str]] = []
    written_artifacts: list[str] = []

    for item in lecture_items:
        lecture = _lecture_session(item, blueprint, source_refs)
        markdown_path, json_path, cue_path = _lecture_artifact_paths(item)
        store.write_markdown(markdown_path, _lecture_markdown(lecture))
        store.write_json(json_path, lecture)
        store.write_json(cue_path, {"cues": lecture.vr_cues, "lecture_id": lecture.lecture_id})
        for path in (markdown_path, json_path, cue_path):
            record_artifact_complete(course_root, "lectures", path)
            written_artifacts.append(path)
        manifest_entries.extend(
            [
                (f"{lecture.lecture_id}_markdown", "markdown", markdown_path),
                (f"{lecture.lecture_id}_json", "json", json_path),
                (f"{lecture.lecture_id}_vr_cues", "json", cue_path),
            ]
        )

    update_manifest_artifacts(course_root, manifest_entries)
    complete_stage(course_root, "lectures", written_artifacts)
    return written_artifacts


def regenerate_lecture_artifact(course_root: str | Path, *, week: int, day: int) -> list[str]:
    """Regenerate one lecture and its VR cue."""

    store = ArtifactStore(course_root)
    item = _find_lecture_item(store, week=week, day=day)
    return _write_selected_lectures(course_root, [item], regenerated=True)


def generate_lecture_week_range(
    course_root: str | Path,
    *,
    start_week: int,
    end_week: int,
) -> list[str]:
    """Regenerate all lectures within an inclusive week range."""

    store = ArtifactStore(course_root)
    schedule: dict[str, Any] = store.read_json("schedule.json")
    items = [
        item
        for item in schedule.get("items", [])
        if item.get("type") == "lecture" and start_week <= int(item["week"]) <= end_week
    ]
    if not items:
        raise LectureGenerationError(f"No lectures found for week range {start_week}-{end_week}.")
    return _write_selected_lectures(course_root, items, regenerated=True)


def _write_selected_lectures(
    course_root: str | Path,
    items: list[dict[str, Any]],
    *,
    regenerated: bool,
) -> list[str]:
    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise LectureGenerationError("Cannot generate lectures before planning and approval.")
    start_stage(course_root, "lectures")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    source_refs = _source_refs(store)
    written: list[str] = []
    manifest_entries: list[tuple[str, str, str] | tuple[str, str, str, dict[str, Any]]] = []
    metadata = {"regenerated": True} if regenerated else {}

    for item in items:
        lecture = _lecture_session(item, blueprint, source_refs)
        markdown_path, json_path, cue_path = _lecture_artifact_paths(item)
        store.write_markdown(markdown_path, _lecture_markdown(lecture))
        store.write_json(json_path, lecture)
        store.write_json(cue_path, {"cues": lecture.vr_cues, "lecture_id": lecture.lecture_id})
        for path in (markdown_path, json_path, cue_path):
            record_artifact_complete(course_root, "lectures", path)
            written.append(path)
        manifest_entries.extend(
            [
                (f"{lecture.lecture_id}_markdown", "markdown", markdown_path, metadata),
                (f"{lecture.lecture_id}_json", "json", json_path, metadata),
                (f"{lecture.lecture_id}_vr_cues", "json", cue_path, metadata),
            ]
        )
    update_manifest_artifacts(course_root, manifest_entries)
    complete_stage(course_root, "lectures", written)
    return written


def _find_lecture_item(store: ArtifactStore, *, week: int, day: int) -> dict[str, Any]:
    schedule: dict[str, Any] = store.read_json("schedule.json")
    for item in schedule.get("items", []):
        if item.get("type") == "lecture" and int(item["week"]) == week and int(item["day"]) == day:
            return item
    raise LectureGenerationError(f"No lecture found for week {week}, day {day}.")


def _lecture_session(
    item: dict[str, Any],
    blueprint: CourseBlueprint,
    source_refs: list[str],
) -> LectureSession:
    lecture_id = str(item["id"])
    title = str(item["title"])
    week = int(item["week"])
    day = int(item["day"])
    objectives = [
        blueprint.outcomes[(week + day - 2) % len(blueprint.outcomes)],
        f"Connect week {week} material to the overall course plan.",
    ]
    transcript = (
        f"Welcome to {title}. We begin by situating this topic inside "
        f"{blueprint.course_title}. The session introduces the core ideas, works through "
        "a concrete example, checks for understanding, and closes with a summary that "
        "prepares students for the next scheduled activity."
    )
    cue = VRHandoffCue(
        cue_id=f"cue_{lecture_id}_opening",
        artifact_id=lecture_id,
        timestamp_or_segment="opening",
        scene_type="lecture_hall",
        professor_action="introduce objectives and write key terms on the board",
        visual_aid=f"{title} board outline",
        interaction_anchor=f"{lecture_id}_opening_question",
    )
    return LectureSession(
        lecture_id=lecture_id,
        week=week,
        day=day,
        title=title,
        objectives=objectives,
        transcript=transcript,
        source_refs=source_refs,
        estimated_duration=float(item.get("duration_hours", 2.0)),
        vr_cues=[cue],
    )


def _lecture_artifact_paths(item: dict[str, Any]) -> tuple[str, str, str]:
    week = int(item["week"])
    day = int(item["day"])
    lecture_id = str(item["id"])
    base = f"lectures/week_{week:02d}/day_{day:02d}"
    return (
        f"{base}.md",
        f"{base}.json",
        f"vr_handoff/lecture_scene_cues/{lecture_id}.json",
    )


def _lecture_markdown(lecture: LectureSession) -> str:
    lines = [
        f"# {lecture.title}",
        "",
        f"Lecture ID: {lecture.lecture_id}",
        f"Week {lecture.week}, Day {lecture.day}",
        "",
        "## Objectives",
        *[f"- {objective}" for objective in lecture.objectives],
        "",
        "## Transcript",
        lecture.transcript,
        "",
        "## Source References",
    ]
    if lecture.source_refs:
        lines.extend(f"- {source_ref}" for source_ref in lecture.source_refs)
    else:
        lines.append("- No local source references.")
    return "\n".join(lines) + "\n"


def _source_refs(store: ArtifactStore) -> list[str]:
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return []
    chunk_manifest: dict[str, Any] = store.read_json("source_index/chunk_manifest.json")
    return sorted(
        {
            str(chunk["source_ref"]).split("!", maxsplit=1)[0]
            for chunk in chunk_manifest.get("chunks", [])
            if chunk.get("source_ref")
        }
    )
