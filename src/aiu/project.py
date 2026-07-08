"""Project initialization for AI University course packages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.config import CourseSettings
from aiu.models import ArtifactIndexEntry, CourseManifest
from aiu.paths import ProjectPaths, project_paths
from aiu.prompt import prompt_sha256
from aiu.state import complete_stage, initialize_state
from aiu.version import __version__

DEFAULT_COURSE_TITLE = "Untitled AI University Course"


class ProjectInitializationError(ValueError):
    """Raised when a course project cannot be initialized safely."""


@dataclass(frozen=True)
class InitializedProject:
    """Result of a successful project initialization."""

    paths: ProjectPaths
    course_id: str
    created_at: str


def initialize_project(
    output_path: str | Path,
    *,
    force: bool = False,
    settings: CourseSettings | None = None,
    created_at: datetime | None = None,
) -> InitializedProject:
    """Create an empty AI University project directory."""

    paths = project_paths(output_path)
    _validate_output_path(paths.root, force=force)

    paths.root.mkdir(parents=True, exist_ok=True)
    for directory in paths.required_directories:
        directory.mkdir(parents=True, exist_ok=True)

    timestamp = _iso_timestamp(created_at)
    course_id = stable_course_id(paths.root)
    settings = settings or CourseSettings()
    store = ArtifactStore(paths.root)

    course_config = _course_config(course_id=course_id, created_at=timestamp, settings=settings)
    manifest = _course_manifest(course_id=course_id, created_at=timestamp, settings=settings)

    store.write_yaml("course.yaml", course_config)
    store.write_json("manifest.json", manifest)
    initialize_state(paths.root)
    complete_stage(paths.root, "project", ["course.yaml", "manifest.json"])

    return InitializedProject(paths=paths, course_id=course_id, created_at=timestamp)


def write_project_prompt(project: InitializedProject, prompt_text: str) -> None:
    """Store a prompt and update the project manifest."""

    store = ArtifactStore(project.paths.root)
    store.write_markdown("prompt.md", prompt_text)
    manifest = CourseManifest.model_validate(store.read_json("manifest.json"))
    updated_manifest = manifest.model_copy(
        update={
            "prompt_ref": "prompt.md",
            "prompt_checksum": prompt_sha256(prompt_text),
        }
    )
    store.write_json("manifest.json", updated_manifest)
    complete_stage(project.paths.root, "inputs", ["prompt.md"])


def update_manifest_artifacts(
    course_root: str | Path,
    artifacts: list[tuple[str, str, str] | tuple[str, str, str, dict[str, Any]]],
) -> None:
    """Add or replace artifact index entries in a course manifest."""

    store = ArtifactStore(course_root)
    manifest = CourseManifest.model_validate(store.read_json("manifest.json"))
    replacement_by_id: dict[str, ArtifactIndexEntry] = {}
    for artifact in artifacts:
        artifact_id, kind, path = artifact[:3]
        metadata = artifact[3] if len(artifact) == 4 else {}
        replacement_by_id[artifact_id] = ArtifactIndexEntry(
            artifact_id=artifact_id,
            kind=kind,
            path=path,
            metadata=metadata,
        )
    kept_entries = [
        entry for entry in manifest.artifact_index if entry.artifact_id not in replacement_by_id
    ]
    updated_manifest = manifest.model_copy(
        update={
            "artifact_index": [
                *kept_entries,
                *[replacement_by_id[key] for key in sorted(replacement_by_id)],
            ]
        }
    )
    store.write_json("manifest.json", updated_manifest)


def stable_course_id(root: str | Path) -> str:
    """Generate a deterministic course ID for a project root."""

    normalized_root = Path(root).expanduser().resolve(strict=False).as_posix()
    digest = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()[:12]
    return f"course_{digest}"


def _validate_output_path(root: Path, *, force: bool) -> None:
    if root.exists() and not root.is_dir():
        raise ProjectInitializationError(f"Output path exists and is not a directory: {root}")

    if root.exists() and any(root.iterdir()) and not force:
        raise ProjectInitializationError(
            f"Refusing to initialize non-empty directory without --force: {root}"
        )


def _course_config(
    *,
    course_id: str,
    created_at: str,
    settings: CourseSettings,
) -> dict[str, Any]:
    return {
        "course_id": course_id,
        "title": DEFAULT_COURSE_TITLE,
        "version": __version__,
        "created_at": created_at,
        "settings": settings.model_dump(mode="json"),
        "paths": {
            "manifest": "manifest.json",
            "artifacts": "artifacts",
            "logs": "logs",
            "vr_handoff": "vr_handoff",
        },
    }


def _course_manifest(
    *,
    course_id: str,
    created_at: str,
    settings: CourseSettings,
) -> CourseManifest:
    return CourseManifest(
        artifact_index=[],
        course_config_ref="course.yaml",
        course_id=course_id,
        created_at=created_at,
        prompt_ref=None,
        prompt_checksum=None,
        provider=settings.provider,
        settings=settings,
        title=DEFAULT_COURSE_TITLE,
        version=__version__,
    )


def _iso_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
