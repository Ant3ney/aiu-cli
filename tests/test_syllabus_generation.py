from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def create_approved_course(tmp_path: Path, *, with_context: bool = False) -> Path:
    course_root = tmp_path / "course"
    args = [
        "course",
        "create",
        "Teach me algorithms",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
    ]
    if with_context:
        materials = tmp_path / "materials"
        materials.mkdir()
        (materials / "notes.md").write_text("# Notes\n\nSource-backed idea.\n", encoding="utf-8")
        args.extend(["--context", str(materials)])
    result = run_aiu(*args, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return course_root


def test_generate_syllabus_stage_writes_course_level_artifacts(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)

    result = run_aiu("course", "generate", str(course_root), "--stage", "syllabus", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    for relative_path in (
        "syllabus/syllabus.md",
        "syllabus/grading_policy.md",
        "syllabus/reading_list.md",
        "study_guides/course_overview.md",
    ):
        assert (course_root / relative_path).is_file()

    manifest = json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in manifest["artifact_index"]} >= {
        "syllabus/syllabus.md",
        "syllabus/grading_policy.md",
        "syllabus/reading_list.md",
        "study_guides/course_overview.md",
    }


def test_syllabus_stage_is_idempotent_unless_forced(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)
    first = run_aiu("course", "generate", str(course_root), "--stage", "syllabus", cwd=tmp_path)
    mtime = (course_root / "syllabus" / "syllabus.md").stat().st_mtime_ns
    second = run_aiu("course", "generate", str(course_root), "--stage", "syllabus", cwd=tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (course_root / "syllabus" / "syllabus.md").stat().st_mtime_ns == mtime


def test_syllabus_includes_source_references_when_chunks_exist(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path, with_context=True)

    result = run_aiu("course", "generate", str(course_root), "--stage", "syllabus", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    reading_list = (course_root / "syllabus" / "reading_list.md").read_text(encoding="utf-8")
    assert "notes.md" in reading_list
