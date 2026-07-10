from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aiu.models import LabSession


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


def create_approved_course(tmp_path: Path, policy: str) -> Path:
    course_root = tmp_path / policy
    result = run_aiu(
        "course",
        "create",
        f"Teach me {policy} labs",
        "--provider",
        "fake",
        "--lab-policy",
        policy,
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_lab_policy_always_creates_one_lab_per_week(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path, "always")

    result = run_aiu("course", "generate", str(course_root), "--stage", "labs", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    lab_markdown = sorted((course_root / "labs").glob("*.md"))
    lab_json = sorted((course_root / "labs").glob("*.json"))
    cue_json = sorted((course_root / "vr_handoff" / "lab_scene_cues").glob("*.json"))

    assert len(lab_markdown) == 24
    assert len(lab_json) == 24
    assert len(cue_json) == 24
    assert LabSession.model_validate(json.loads(lab_json[0].read_text(encoding="utf-8"))).vr_cues
    first_lab = lab_markdown[0].read_text(encoding="utf-8")
    assert "Course Map, Core Vocabulary, and Success Criteria" in first_lab
    assert "course scope for always labs" in first_lab
    assert "Complete a guided practice task" not in first_lab
    assert "Review the week objectives" not in first_lab


def test_lab_policy_never_creates_alternatives_but_no_lab_files(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path, "never")

    result = run_aiu("course", "generate", str(course_root), "--stage", "labs", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert list((course_root / "labs").glob("*.md")) == []
    alternatives = sorted((course_root / "artifacts" / "activities").glob("*.md"))
    assert len(alternatives) == 24
    first_activity = alternatives[0].read_text(encoding="utf-8")
    assert "instead of a lab" in first_activity
    assert "Course Map, Core Vocabulary, and Success Criteria" in first_activity
    assert "discussion, case analysis, or workshop activity" not in first_activity


def test_lab_policy_auto_records_rationale_in_blueprint_and_lab(tmp_path: Path) -> None:
    course_root = create_approved_course(tmp_path, "auto")

    result = run_aiu("course", "generate", str(course_root), "--stage", "labs", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    blueprint = json.loads((course_root / "course_blueprint.json").read_text(encoding="utf-8"))
    lab_text = (course_root / "labs" / "week_01_lab.md").read_text(encoding="utf-8")
    assert "Auto mode" in blueprint["lab_policy_rationale"]
    assert "Policy rationale: Auto mode" in lab_text
