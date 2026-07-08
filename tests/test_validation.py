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


def generated_course(tmp_path: Path) -> Path:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me cryptography",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    generate = run_aiu("course", "generate", str(course_root), cwd=tmp_path)
    assert create.returncode == 0, create.stderr
    assert generate.returncode == 0, generate.stderr
    return course_root


def test_valid_fake_provider_course_validates_with_report(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)

    result = run_aiu("course", "validate", str(course_root), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    report = json.loads((course_root / "validation_report.json").read_text(encoding="utf-8"))
    assert report["status"] in {"pass", "warn"}
    assert report["artifact_counts"]["lectures"] == 48
    assert (course_root / "warnings.md").is_file()


def test_validation_failure_returns_nonzero_and_writes_actionable_report(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)
    (course_root / "schedule.json").unlink()

    result = run_aiu("course", "validate", str(course_root), cwd=tmp_path)

    assert result.returncode != 0
    report = json.loads((course_root / "validation_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert any("schedule.json" in failure for failure in report["failures"])
    assert "Missing required file" in (course_root / "warnings.md").read_text(encoding="utf-8")
