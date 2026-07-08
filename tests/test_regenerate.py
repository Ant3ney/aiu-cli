from __future__ import annotations

import hashlib
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_course(tmp_path: Path) -> Path:
    course_root = tmp_path / "course"
    result = run_aiu(
        "course",
        "create",
        "Teach me compilers",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_regenerate_single_lecture_preserves_unrelated_artifacts(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)
    unrelated = course_root / "lectures" / "week_01" / "day_01.md"
    before = sha256(unrelated)

    regenerate = run_aiu(
        "course",
        "regenerate",
        str(course_root),
        "--artifact",
        "lecture:w08:d01",
        cwd=tmp_path,
    )
    after = sha256(unrelated)
    validate = run_aiu("course", "validate", str(course_root), cwd=tmp_path)

    assert regenerate.returncode == 0, regenerate.stderr
    assert before == after
    assert validate.returncode == 0, validate.stderr

    manifest = json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in manifest["artifact_index"]
        if item["artifact_id"] == "lecture_w08_d01_markdown"
    )
    assert entry["metadata"]["regenerated"] is True


def test_generate_week_range_regenerates_only_selected_weeks(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)
    outside = course_root / "lectures" / "week_01" / "day_01.md"
    before = sha256(outside)

    result = run_aiu(
        "course",
        "generate",
        str(course_root),
        "--from",
        "week:10",
        "--to",
        "week:12",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert sha256(outside) == before
    assert "Regenerated lecture range" in result.stdout
