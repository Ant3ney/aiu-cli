from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_aiu(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.setdefault("PYTHONUTF8", "1")
    if env:
        process_env.update(env)
    aiu_executable = Path(sys.executable).with_name("aiu")
    return subprocess.run(
        [str(aiu_executable), *args],
        cwd=cwd,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def read_state(course_root: Path) -> dict[str, object]:
    return json.loads((course_root / ".aiu" / "state.json").read_text(encoding="utf-8"))


def test_course_create_generate_until_blueprint_writes_checkpoint_state(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        "--generate-until",
        "blueprint",
        cwd=tmp_path,
    )
    status = run_aiu("course", "status", str(course_root), cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert status.returncode == 0, status.stderr
    state = read_state(course_root)
    assert state["stages"]["project"]["status"] == "complete"
    assert state["stages"]["inputs"]["status"] == "complete"
    assert state["stages"]["blueprint"]["status"] == "complete"
    assert state["stages"]["syllabus"]["status"] == "pending"
    assert "blueprint: complete" in status.stdout


def test_failed_blueprint_plan_can_resume_without_rewriting_inputs(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )
    failed = run_aiu(
        "course",
        "plan",
        str(course_root),
        cwd=tmp_path,
        env={"AIU_FAIL_STAGE": "blueprint"},
    )
    before_prompt_state = read_state(course_root)["artifacts"]["prompt.md"]
    resumed = run_aiu("course", "plan", str(course_root), cwd=tmp_path)
    after_prompt_state = read_state(course_root)["artifacts"]["prompt.md"]

    assert create.returncode == 0, create.stderr
    assert failed.returncode != 0
    assert resumed.returncode == 0, resumed.stderr
    assert before_prompt_state == after_prompt_state
    assert read_state(course_root)["stages"]["blueprint"]["status"] == "complete"


def test_completed_blueprint_stage_is_skipped_on_repeated_plan(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )
    first = run_aiu("course", "plan", str(course_root), cwd=tmp_path)
    blueprint_mtime = (course_root / "course_blueprint.json").stat().st_mtime_ns
    second = run_aiu("course", "plan", str(course_root), cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (course_root / "course_blueprint.json").stat().st_mtime_ns == blueprint_mtime


def test_course_resume_continues_from_blueprint_checkpoint(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--weeks",
        "1",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--output",
        str(course_root),
        "--yes",
        "--generate-until",
        "blueprint",
        cwd=tmp_path,
    )
    resumed = run_aiu("course", "resume", str(course_root), "--yes", cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert resumed.returncode == 0, resumed.stderr
    assert "Resumed AI University course package" in resumed.stdout
    assert (course_root / "validation_report.json").is_file()
    assert (course_root / "course_memory.json").is_file()
    state = read_state(course_root)
    assert state["stages"]["validation"]["status"] == "complete"


def test_course_resume_requires_approval_or_yes(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--weeks",
        "1",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--output",
        str(course_root),
        "--generate-until",
        "blueprint",
        cwd=tmp_path,
    )
    resumed = run_aiu("course", "resume", str(course_root), cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert resumed.returncode != 0
    assert "not approved" in resumed.stderr


def test_course_resume_repairs_missing_artifact_without_rewriting_completed_work(
    tmp_path: Path,
) -> None:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
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
        "--yes",
        cwd=tmp_path,
    )
    completed_lecture = course_root / "lectures" / "week_01" / "day_01.md"
    completed_mtime = completed_lecture.stat().st_mtime_ns
    missing_paths = [
        course_root / "lectures" / "week_02" / "day_01.md",
        course_root / "lectures" / "week_02" / "day_01.json",
        course_root / "vr_handoff" / "lecture_scene_cues" / "lecture_w02_d01.json",
    ]
    for path in missing_paths:
        path.unlink()

    resumed = run_aiu("course", "resume", str(course_root), cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert resumed.returncode == 0, resumed.stderr
    assert completed_lecture.stat().st_mtime_ns == completed_mtime
    assert all(path.is_file() for path in missing_paths)
