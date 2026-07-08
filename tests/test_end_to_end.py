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


def test_course_create_yes_runs_full_fake_provider_pipeline(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    create = run_aiu(
        "course",
        "create",
        "Teach me artificial intelligence",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    status = run_aiu("course", "status", str(course_root), cwd=tmp_path)
    validate = run_aiu("course", "validate", str(course_root), cwd=tmp_path)

    assert create.returncode == 0, create.stderr
    assert status.returncode == 0, status.stderr
    assert validate.returncode == 0, validate.stderr
    assert (course_root / "validation_report.json").is_file()
    assert (course_root / "logs" / "aiu.log").is_file()

    report = json.loads((course_root / "validation_report.json").read_text(encoding="utf-8"))
    assert report["status"] in {"pass", "warn"}
    log_text = (course_root / "logs" / "aiu.log").read_text(encoding="utf-8")
    assert "blueprint generated" in log_text
    assert "all generation stages completed" in log_text
