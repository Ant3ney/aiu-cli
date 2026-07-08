"""Course export packaging."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, start_stage

SUPPORTED_EXPORT_FORMATS = {"markdown", "json", "vr"}


class ExportError(ValueError):
    """Raised when export configuration is invalid."""


def export_course(course_root: str | Path, formats: str) -> list[str]:
    """Export generated course materials into requested package formats."""

    requested = _parse_formats(formats)
    store = ArtifactStore(course_root)
    start_stage(course_root, "export")
    artifacts: list[str] = []

    if "markdown" in requested:
        artifacts.extend(_export_markdown(store))
    if "json" in requested:
        artifacts.extend(_export_json(store))
    if "vr" in requested:
        artifacts.extend(_export_vr(store))

    update_manifest_artifacts(
        course_root,
        [
            (f"export_{index:03d}", "export", artifact)
            for index, artifact in enumerate(artifacts, start=1)
        ],
    )
    complete_stage(course_root, "export", artifacts)
    return artifacts


def _parse_formats(formats: str) -> set[str]:
    requested = {item.strip().lower() for item in formats.split(",") if item.strip()}
    invalid = requested - SUPPORTED_EXPORT_FORMATS
    if invalid:
        raise ExportError(f"Unsupported export format(s): {', '.join(sorted(invalid))}")
    return requested or set(SUPPORTED_EXPORT_FORMATS)


def _export_markdown(store: ArtifactStore) -> list[str]:
    artifacts: list[str] = []
    roots = [
        "syllabus",
        "lectures",
        "labs",
        "homework",
        "quizzes",
        "exams",
        "projects",
        "rubrics",
        "answer_keys",
        "study_guides",
    ]
    for root_name in roots:
        source_root = store.root / root_name
        if not source_root.exists():
            continue
        for source_path in sorted(source_root.rglob("*.md")):
            relative = source_path.relative_to(store.root).as_posix()
            target_relative = f"exports/markdown/{relative}"
            _copy_file(source_path, store.course_path(target_relative))
            artifacts.append(target_relative)
    return artifacts


def _export_json(store: ArtifactStore) -> list[str]:
    artifacts: list[str] = []
    json_roots = [
        "lectures",
        "labs",
        "homework",
        "quizzes",
        "exams",
        "projects",
        "source_index",
        "vr_handoff",
    ]
    top_level = [
        "manifest.json",
        "source_manifest.json",
        "ingest_report.json",
        "intent_analysis.json",
        "course_blueprint.json",
        "approved_course_blueprint.json",
        "approval_metadata.json",
        "schedule.json",
        "validation_report.json",
    ]
    for relative in top_level:
        source_path = store.course_path(relative)
        if source_path.exists():
            target_relative = f"exports/json/{relative}"
            _copy_file(source_path, store.course_path(target_relative))
            artifacts.append(target_relative)
    for root_name in json_roots:
        source_root = store.root / root_name
        if not source_root.exists():
            continue
        for source_path in sorted(source_root.rglob("*.json")):
            relative = source_path.relative_to(store.root).as_posix()
            target_relative = f"exports/json/{relative}"
            _copy_file(source_path, store.course_path(target_relative))
            artifacts.append(target_relative)
    return artifacts


def _export_vr(store: ArtifactStore) -> list[str]:
    runtime_manifest = _runtime_manifest(store)
    artifacts = ["vr_handoff/course_runtime_manifest.json"]
    store.write_json("vr_handoff/course_runtime_manifest.json", runtime_manifest)
    store.write_json("exports/vr/course_runtime_manifest.json", runtime_manifest)
    artifacts.append("exports/vr/course_runtime_manifest.json")

    for cue_root_name in ("lecture_scene_cues", "lab_scene_cues"):
        cue_root = store.root / "vr_handoff" / cue_root_name
        if not cue_root.exists():
            continue
        for source_path in sorted(cue_root.glob("*.json")):
            relative = source_path.relative_to(store.root).as_posix()
            target_relative = f"exports/vr/{relative}"
            _copy_file(source_path, store.course_path(target_relative))
            artifacts.append(target_relative)
    return artifacts


def _runtime_manifest(store: ArtifactStore) -> dict[str, Any]:
    lecture_cues = _cue_entries(store, "lecture_scene_cues", "lecture_id")
    lab_cues = _cue_entries(store, "lab_scene_cues", "lab_id")
    return {
        "completion_state_hooks": {
            "course_started": "course:start",
            "lecture_completed": "lecture:complete",
            "lab_completed": "lab:complete",
            "assessment_completed": "assessment:complete",
        },
        "lab_scene_cues": lab_cues,
        "lecture_scene_cues": lecture_cues,
        "redacted_absolute_paths": True,
        "schedule_ref": "schedule.json",
        "version": 1,
    }


def _cue_entries(store: ArtifactStore, cue_root_name: str, id_field: str) -> list[dict[str, str]]:
    cue_root = store.root / "vr_handoff" / cue_root_name
    if not cue_root.exists():
        return []
    entries: list[dict[str, str]] = []
    for path in sorted(cue_root.glob("*.json")):
        relative = path.relative_to(store.root).as_posix()
        data = store.read_json(relative)
        entries.append(
            {
                id_field: str(data.get(id_field, path.stem)),
                "path": relative,
            }
        )
    return entries


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
