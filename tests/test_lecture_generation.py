from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aiu.models import LectureSession


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
        "Teach me networking",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_generate_lectures_stage_writes_default_lecture_and_vr_artifacts(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)

    result = run_aiu("course", "generate", str(course_root), "--stage", "lectures", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    lecture_md = sorted((course_root / "lectures").rglob("*.md"))
    lecture_json = sorted((course_root / "lectures").rglob("*.json"))
    cue_json = sorted((course_root / "vr_handoff" / "lecture_scene_cues").rglob("*.json"))

    assert len(lecture_md) == 48
    assert len(lecture_json) == 48
    assert len(cue_json) == 48


def test_every_lecture_json_validates_and_has_vr_cue(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path)
    result = run_aiu("course", "generate", str(course_root), "--stage", "lectures", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    for path in sorted((course_root / "lectures").rglob("*.json")):
        lecture = LectureSession.model_validate(json.loads(path.read_text(encoding="utf-8")))
        assert lecture.vr_cues

    state = json.loads((course_root / ".aiu" / "state.json").read_text(encoding="utf-8"))
    assert state["stages"]["lectures"]["status"] == "complete"
    assert len(state["stages"]["lectures"]["artifacts"]) == 144
