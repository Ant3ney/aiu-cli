from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiu.artifact_store import ArtifactStore, ArtifactWriteError
from aiu.config import CourseSettings
from aiu.models import CourseManifest


def test_artifact_store_writes_stable_json_yaml_and_markdown(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    manifest = CourseManifest(
        course_id="course_123",
        title="Example",
        version="0.1.0",
        prompt_ref="prompt.md",
        settings=CourseSettings(),
        created_at="2026-07-08T10:00:00Z",
        provider="fake",
    )

    json_path = store.write_json("manifest.json", manifest)
    yaml_path = store.write_yaml("course.yaml", {"title": "Example", "paths": {"logs": "logs"}})
    markdown_path = store.write_markdown("syllabus/syllabus.md", "# Syllabus\n")

    assert json.loads(json_path.read_text(encoding="utf-8"))["settings"]["weeks"] == 24
    assert json_path.read_text(encoding="utf-8").endswith("\n")
    assert yaml_path.read_text(encoding="utf-8").startswith("title: Example\n")
    assert markdown_path.read_text(encoding="utf-8") == "# Syllabus\n"


def test_artifact_store_normalizes_manifest_paths(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    assert store.portable_path(tmp_path / "lectures" / "week_01" / "day_01.md") == (
        "lectures/week_01/day_01.md"
    )
    assert store.course_path("lectures\\week_01\\day_01.md") == (
        tmp_path / "lectures" / "week_01" / "day_01.md"
    )

    with pytest.raises(ValueError):
        store.course_path("../outside.json")


def test_atomic_write_keeps_existing_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path)
    target = tmp_path / "manifest.json"
    target.write_text('{"valid": true}\n', encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store, "_replace", fail_replace)

    with pytest.raises(ArtifactWriteError):
        store.write_json("manifest.json", {"valid": False})

    assert target.read_text(encoding="utf-8") == '{"valid": true}\n'
    assert not list(tmp_path.glob(".manifest.json.*.tmp"))
