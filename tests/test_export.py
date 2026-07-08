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
    result = run_aiu(
        "course",
        "create",
        "Teach me data science",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_course_export_creates_requested_formats_and_vr_manifest(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)

    result = run_aiu(
        "course",
        "export",
        str(course_root),
        "--format",
        "markdown,json,vr",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (course_root / "exports" / "markdown").is_dir()
    assert (course_root / "exports" / "json").is_dir()
    assert (course_root / "exports" / "vr").is_dir()
    assert (course_root / "vr_handoff" / "course_runtime_manifest.json").is_file()

    runtime_manifest = json.loads(
        (course_root / "vr_handoff" / "course_runtime_manifest.json").read_text(encoding="utf-8")
    )
    assert runtime_manifest["lecture_scene_cues"]
    first_cue = runtime_manifest["lecture_scene_cues"][0]["path"]
    assert (course_root / first_cue).is_file()


def test_exported_json_does_not_include_absolute_course_root(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)

    result = run_aiu("course", "export", str(course_root), "--format", "json,vr", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    exported_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((course_root / "exports").rglob("*.json"))
    )
    assert str(course_root) not in exported_text


def test_course_export_rejects_unknown_format(tmp_path: Path) -> None:
    course_root = generated_course(tmp_path)

    result = run_aiu("course", "export", str(course_root), "--format", "pdf", cwd=tmp_path)

    assert result.returncode != 0
    assert "Unsupported export format" in result.stderr
