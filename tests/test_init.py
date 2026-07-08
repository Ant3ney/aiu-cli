from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from aiu.paths import REQUIRED_PROJECT_DIRECTORIES


def run_aiu(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    aiu_executable = Path(sys.executable).with_name("aiu")
    return subprocess.run(
        [str(aiu_executable), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def read_manifest(course_root: Path) -> dict[str, object]:
    return json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))


def test_init_creates_required_layout_and_metadata(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    result = run_aiu("init", "--output", str(course_root), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    for directory in REQUIRED_PROJECT_DIRECTORIES:
        assert (course_root / directory).is_dir()
    assert (course_root / "course.yaml").is_file()

    manifest = read_manifest(course_root)
    assert manifest["course_config_ref"] == "course.yaml"
    assert manifest["prompt_ref"] is None
    assert manifest["artifact_index"] == []
    assert manifest["provider"] == "fake"
    assert isinstance(manifest["course_id"], str)
    assert manifest["course_id"].startswith("course_")

    created_at = str(manifest["created_at"])
    assert created_at.endswith("Z")
    parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert parsed_created_at.tzinfo is not None


def test_init_refuses_existing_non_empty_directory_without_force(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    course_root.mkdir()
    (course_root / "notes.txt").write_text("keep me\n", encoding="utf-8")

    result = run_aiu("init", "--output", str(course_root), cwd=tmp_path)

    assert result.returncode != 0
    assert "Refusing to initialize non-empty directory without --force" in result.stderr
    assert not (course_root / "manifest.json").exists()
    assert (course_root / "notes.txt").read_text(encoding="utf-8") == "keep me\n"


def test_init_force_allows_existing_non_empty_directory(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    course_root.mkdir()
    sentinel = course_root / "notes.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    first_result = run_aiu("init", "--output", str(course_root), "--force", cwd=tmp_path)
    first_manifest = read_manifest(course_root)

    second_result = run_aiu("init", "--output", str(course_root), "--force", cwd=tmp_path)
    second_manifest = read_manifest(course_root)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep me\n"
    assert first_manifest["course_id"] == second_manifest["course_id"]
    assert second_manifest["course_config_ref"] == "course.yaml"
