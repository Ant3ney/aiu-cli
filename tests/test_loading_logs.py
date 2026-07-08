from __future__ import annotations

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


def test_course_create_streams_loading_logs_and_content_previews(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    result = run_aiu(
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
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "AI University course creation" in result.stdout
    assert "Created lecture transcript" in result.stdout
    assert "preview:" in result.stdout
    assert "while you wait:" in result.stdout

    log_text = (course_root / "logs" / "aiu.log").read_text(encoding="utf-8")
    assert "course loading view started" in log_text
    assert "Created lecture transcript" in log_text
    assert "preview=" in log_text
    assert "course loading view completed" in log_text
