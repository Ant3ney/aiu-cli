from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def run_aiu(
    *args: str,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    aiu_executable = Path(sys.executable).with_name("aiu")
    return subprocess.run(
        [str(aiu_executable), *args],
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def read_manifest(course_root: Path) -> dict[str, object]:
    return json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))


def prompt_checksum(prompt_text: str) -> str:
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def test_course_create_accepts_prompt_argument(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    prompt = "Teach me distributed systems"

    result = run_aiu(
        "course",
        "create",
        prompt,
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (course_root / "prompt.md").read_text(encoding="utf-8") == prompt

    manifest = read_manifest(course_root)
    assert manifest["prompt_ref"] == "prompt.md"
    assert manifest["prompt_checksum"] == prompt_checksum(prompt)
    assert manifest["settings"] == {
        "lab_policy": "auto",
        "lecture_hours": 2.0,
        "lectures_per_week": 2,
        "level": "beginner",
        "provider": "fake",
        "weeks": 24,
    }


def test_course_create_accepts_prompt_file(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    prompt_file = tmp_path / "prompt.md"
    prompt = "Teach me compilers\nfrom parsing to optimization.\n"
    prompt_file.write_text(prompt, encoding="utf-8")

    result = run_aiu(
        "course",
        "create",
        "--prompt",
        str(prompt_file),
        "--output",
        str(course_root),
        "--weeks",
        "12",
        "--level",
        "intermediate",
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (course_root / "prompt.md").read_text(encoding="utf-8") == prompt

    manifest = read_manifest(course_root)
    assert manifest["prompt_ref"] == "prompt.md"
    assert manifest["prompt_checksum"] == prompt_checksum(prompt)
    assert manifest["settings"]["weeks"] == 12
    assert manifest["settings"]["level"] == "intermediate"


def test_course_create_accepts_stdin_prompt(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    prompt = "Teach me compilers\n"

    result = run_aiu(
        "course",
        "create",
        "--stdin",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
        input_text=prompt,
    )

    assert result.returncode == 0, result.stderr
    assert (course_root / "prompt.md").read_text(encoding="utf-8") == prompt
    assert read_manifest(course_root)["prompt_checksum"] == prompt_checksum(prompt)


def test_course_create_rejects_missing_prompt_source(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    result = run_aiu("course", "create", "--output", str(course_root), "--init-only", cwd=tmp_path)

    assert result.returncode != 0
    assert "Use exactly one prompt source" in result.stderr
    assert not course_root.exists()


def test_course_create_rejects_multiple_prompt_sources(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Teach me databases", encoding="utf-8")

    result = run_aiu(
        "course",
        "create",
        "Teach me networks",
        "--prompt",
        str(prompt_file),
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "Use exactly one prompt source" in result.stderr
    assert not course_root.exists()


def test_course_create_rejects_empty_prompt(tmp_path: Path) -> None:
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "--stdin",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
        input_text="\n\t\n",
    )

    assert result.returncode != 0
    assert "Prompt text cannot be empty" in result.stderr
    assert not course_root.exists()
