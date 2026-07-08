"""Project path conventions for AI University course packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_PROJECT_DIRECTORIES: tuple[str, ...] = (
    "logs",
    "artifacts",
    "source_index",
    "extracted_sources",
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
    "vr_handoff",
    "exports",
)


@dataclass(frozen=True)
class ProjectPaths:
    """Resolved filesystem locations for an AI University project."""

    root: Path
    course_config: Path
    manifest: Path
    prompt: Path
    logs: Path
    artifacts: Path

    @property
    def required_directories(self) -> tuple[Path, ...]:
        """Return the PRD-required project directories beneath the root."""

        return tuple(self.root / directory for directory in REQUIRED_PROJECT_DIRECTORIES)


def project_paths(root: str | Path) -> ProjectPaths:
    """Build path references for a course project root without touching the filesystem."""

    resolved_root = Path(root).expanduser()
    return ProjectPaths(
        root=resolved_root,
        course_config=resolved_root / "course.yaml",
        manifest=resolved_root / "manifest.json",
        prompt=resolved_root / "prompt.md",
        logs=resolved_root / "logs",
        artifacts=resolved_root / "artifacts",
    )
