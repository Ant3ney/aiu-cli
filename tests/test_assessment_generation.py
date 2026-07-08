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


def create_approved_course(tmp_path: Path) -> Path:
    course_root = tmp_path / "course"
    result = run_aiu(
        "course",
        "create",
        "Teach me software engineering",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_generate_assessments_creates_homework_quizzes_exams_and_project(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)

    result = run_aiu("course", "generate", str(course_root), "--stage", "assessments", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert len(list((course_root / "homework").glob("*.md"))) >= 24
    assert len(list((course_root / "quizzes").glob("*.md"))) >= 12
    assert (course_root / "exams" / "midterm.md").is_file()
    assert (course_root / "exams" / "final.md").is_file()
    assert (course_root / "projects" / "course_project.md").is_file()
    assert len(list((course_root / "rubrics").glob("*.md"))) > 0
    assert len(list((course_root / "answer_keys").glob("*.md"))) > 0


def test_every_graded_artifact_has_rubric_and_answer_key(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)
    result = run_aiu("course", "generate", str(course_root), "--stage", "assessments", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assessment_ids = [
        *[path.stem for path in (course_root / "homework").glob("*.md")],
        *[path.stem for path in (course_root / "quizzes").glob("*.md")],
        "midterm",
        "final",
        "course_project",
    ]
    for assessment_id in assessment_ids:
        assert (course_root / "rubrics" / f"{assessment_id}.md").is_file()
        assert (course_root / "answer_keys" / f"{assessment_id}.md").is_file()


def test_assessments_reference_learning_objectives_and_manifest_entries(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)
    result = run_aiu("course", "generate", str(course_root), "--stage", "assessments", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    homework = json.loads(
        (course_root / "homework" / "homework_w01.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))

    assert homework["objectives"]
    assert "learning" in " ".join(homework["objectives"]).lower() or homework["objectives"][0]
    assert any(entry["path"] == "homework/homework_w01.md" for entry in manifest["artifact_index"])
