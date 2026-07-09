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


def test_course_create_generate_until_syllabus_stops_before_full_generation(
    tmp_path: Path,
) -> None:
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me creature collector RPG design",
        "--provider",
        "fake",
        "--weeks",
        "2",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--output",
        str(course_root),
        "--generate-until",
        "syllabus",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "Generated syllabus preview" in result.stdout
    assert (course_root / "approved_course_blueprint.json").is_file()
    assert (course_root / "syllabus" / "syllabus.md").is_file()
    assert not (course_root / "lectures" / "week_01" / "day_01.md").exists()
    assert not (course_root / "validation_report.json").exists()

    state = json.loads((course_root / ".aiu" / "state.json").read_text(encoding="utf-8"))
    assert state["stages"]["approval"]["status"] == "complete"
    assert state["stages"]["syllabus"]["status"] == "complete"
    assert state["stages"]["lectures"]["status"] == "pending"
    assert state["stages"]["validation"]["status"] == "pending"


def test_course_feedback_regenerates_blueprint_and_syllabus_preview(
    tmp_path: Path,
) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me creature collector RPG design",
        "--provider",
        "fake",
        "--weeks",
        "3",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--output",
        str(course_root),
        "--generate-until",
        "syllabus",
        cwd=tmp_path,
    )
    feedback = run_aiu(
        "course",
        "feedback",
        str(course_root),
        "Include creature stat schemas and evolution rules.",
        cwd=tmp_path,
    )

    assert create.returncode == 0, create.stderr
    assert feedback.returncode == 0, feedback.stderr
    assert "Applied course feedback" in feedback.stdout

    feedback_markdown = (course_root / "course_feedback.md").read_text(encoding="utf-8")
    blueprint_markdown = (course_root / "course_blueprint.md").read_text(encoding="utf-8")
    syllabus_markdown = (course_root / "syllabus" / "syllabus.md").read_text(
        encoding="utf-8"
    )
    approved_blueprint = json.loads(
        (course_root / "approved_course_blueprint.json").read_text(encoding="utf-8")
    )
    approval_metadata = json.loads(
        (course_root / "approval_metadata.json").read_text(encoding="utf-8")
    )

    assert "Include creature stat schemas and evolution rules." in feedback_markdown
    assert "Learner feedback priority: Include creature stat schemas" in blueprint_markdown
    assert "Learner feedback priority: Include creature stat schemas" in syllabus_markdown
    assert any(
        "creature stat schemas" in topic
        for week in approved_blueprint["week_plan"]
        for topic in week["topics"]
    )
    assert approval_metadata["approval_mode"] == "feedback"


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
