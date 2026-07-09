from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


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


def generated_short_course(tmp_path: Path) -> Path:
    course_root = tmp_path / "course"
    result = run_aiu(
        "course",
        "create",
        "Teach me deterministic teaching runtimes",
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
    assert result.returncode == 0, result.stderr
    return course_root


def test_full_generation_writes_deterministic_course_rails(tmp_path: Path) -> None:
    course_root = generated_short_course(tmp_path)

    rails = json.loads((course_root / "rails.json").read_text(encoding="utf-8"))
    report = json.loads((course_root / "validation_report.json").read_text(encoding="utf-8"))
    state = json.loads((course_root / ".aiu" / "state.json").read_text(encoding="utf-8"))

    assert rails["schema"] == {"name": "aiu.course_rails", "version": 1}
    assert rails["runtime_contract"]["deterministic_reader"] is True
    assert rails["course"]["refs"]["schedule"] == "schedule.json"
    assert len(rails["artifact_catalog"]["lectures"]) == 2
    assert len(rails["weeks"]) == 2
    assert rails["day_by_day_plan"]
    assert [session["sequence"] for session in rails["day_by_day_plan"]] == list(
        range(1, len(rails["day_by_day_plan"]) + 1)
    )
    assert state["stages"]["rails"]["status"] == "complete"
    assert report["artifact_counts"]["rails"] == 1

    lecture_session = next(
        session for session in rails["day_by_day_plan"] if session["session_type"] == "lecture"
    )
    action_types = [action["type"] for action in lecture_session["presentation_actions"]]
    assert "present_transcript" in action_types
    assert "present_scene_cues" in action_types

    for ref in path_refs(rails):
        assert not Path(ref).is_absolute()
        assert (course_root / ref).exists(), ref


def test_generate_rails_stage_rebuilds_runtime_contract(tmp_path: Path) -> None:
    course_root = generated_short_course(tmp_path)
    rails_path = course_root / "rails.json"
    rails_path.unlink()

    result = run_aiu("course", "generate", str(course_root), "--stage", "rails", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert rails_path.is_file()
    assert "Generated rails stage" in result.stdout


def test_validation_fails_when_rails_file_is_missing(tmp_path: Path) -> None:
    course_root = generated_short_course(tmp_path)
    (course_root / "rails.json").unlink()

    result = run_aiu("course", "validate", str(course_root), cwd=tmp_path)

    assert result.returncode != 0
    report = json.loads((course_root / "validation_report.json").read_text(encoding="utf-8"))
    assert any("rails.json" in failure for failure in report["failures"])


def path_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if is_path_key(str(key)) and isinstance(child, str):
                refs.append(child)
            else:
                refs.extend(path_refs(child))
    elif isinstance(value, list):
        for item in value:
            refs.extend(path_refs(item))
    return refs


def is_path_key(key: str) -> bool:
    return key.endswith("_ref") or key in {
        "approved_blueprint",
        "blueprint",
        "manifest",
        "path",
        "schedule",
    }
