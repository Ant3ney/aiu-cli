"""Selective regeneration helpers."""

from __future__ import annotations

import re
from pathlib import Path

from aiu.lecture_generation import generate_lecture_week_range, regenerate_lecture_artifact
from aiu.logging import ProgressCallback


class RegenerationError(ValueError):
    """Raised when a regeneration reference cannot be handled."""


def regenerate_artifact(
    course_root: str | Path,
    artifact_ref: str,
    *,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Regenerate a selected artifact reference."""

    match = re.fullmatch(r"lecture:w(?P<week>\d+):d(?P<day>\d+)", artifact_ref)
    if not match:
        raise RegenerationError(f"Unsupported artifact reference: {artifact_ref}")
    return regenerate_lecture_artifact(
        course_root,
        week=int(match.group("week")),
        day=int(match.group("day")),
        progress=progress,
    )


def regenerate_week_range(
    course_root: str | Path,
    from_ref: str,
    to_ref: str,
    *,
    progress: ProgressCallback | None = None,
) -> list[str]:
    """Regenerate lectures for an inclusive week range."""

    start_week = _parse_week_ref(from_ref)
    end_week = _parse_week_ref(to_ref)
    if end_week < start_week:
        raise RegenerationError("--to week must be greater than or equal to --from week.")
    return generate_lecture_week_range(
        course_root,
        start_week=start_week,
        end_week=end_week,
        progress=progress,
    )


def _parse_week_ref(value: str) -> int:
    match = re.fullmatch(r"week:(?P<week>\d+)", value)
    if not match:
        raise RegenerationError(f"Unsupported week reference: {value}")
    return int(match.group("week"))
