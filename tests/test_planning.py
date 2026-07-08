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


def create_course(tmp_path: Path, *extra_args: str) -> Path:
    course_root = tmp_path / f"course-{len(list(tmp_path.iterdir()))}"
    result = run_aiu(
        "course",
        "create",
        "Teach me machine learning",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--init-only",
        *extra_args,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return course_root


def test_course_plan_generates_blueprint_and_default_schedule(tmp_path: Path) -> None:
    course_root = create_course(tmp_path)

    result = run_aiu("course", "plan", str(course_root), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    blueprint = json.loads((course_root / "course_blueprint.json").read_text(encoding="utf-8"))
    schedule = json.loads((course_root / "schedule.json").read_text(encoding="utf-8"))
    manifest = json.loads((course_root / "manifest.json").read_text(encoding="utf-8"))

    assert blueprint["course_title"] == "Machine Learning: AI University Course"
    assert blueprint["outcomes"]
    assert blueprint["prerequisites"]
    assert blueprint["modules"]
    assert blueprint["week_plan"]
    assert blueprint["assessment_plan"]
    assert blueprint["source_usage_plan"]
    assert blueprint["lab_policy"] == "auto"

    lectures = [item for item in schedule["items"] if item["type"] == "lecture"]
    assert len(lectures) == 48
    assert {entry["path"] for entry in manifest["artifact_index"]} >= {
        "intent_analysis.json",
        "course_blueprint.json",
        "course_blueprint.md",
        "schedule.json",
    }


def test_course_plan_honors_custom_week_and_lecture_counts(tmp_path: Path) -> None:
    course_root = create_course(tmp_path, "--weeks", "3", "--lectures-per-week", "1")

    result = run_aiu("course", "plan", str(course_root), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    schedule = json.loads((course_root / "schedule.json").read_text(encoding="utf-8"))
    lectures = [item for item in schedule["items"] if item["type"] == "lecture"]
    assert len(lectures) == 3
    assert schedule["lecture_count"] == 3


def test_course_plan_requires_stored_prompt(tmp_path: Path) -> None:
    course_root = tmp_path / "course"
    init = run_aiu("init", "--output", str(course_root), cwd=tmp_path)
    result = run_aiu("course", "plan", str(course_root), cwd=tmp_path)

    assert init.returncode == 0, init.stderr
    assert result.returncode != 0
    assert "Cannot plan a course before prompt.md is stored" in result.stderr


def test_course_plan_uses_configured_codex_provider_without_api_key(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    codex_bin = write_fake_codex(tmp_path)
    env = {
        "AIU_CONFIG_HOME": str(config_home),
        "PATH": f"{codex_bin.parent}:{os.environ['PATH']}",
    }
    auth = run_aiu("auth", "login", "--provider", "codex", cwd=tmp_path, env=env)
    course_root = tmp_path / "course-codex"
    create = run_aiu(
        "course",
        "create",
        "Teach me machine learning",
        "--provider",
        "codex",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
        env=env,
    )
    plan = run_aiu("course", "plan", str(course_root), cwd=tmp_path, env=env)

    assert auth.returncode == 0, auth.stderr
    assert create.returncode == 0, create.stderr
    assert plan.returncode == 0, plan.stderr
    intent = json.loads((course_root / "intent_analysis.json").read_text(encoding="utf-8"))
    assert intent["provider"] == "codex"
    assert intent["provider_plan_seed"] == "Codex planning guidance"


def write_fake_codex(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex_bin = bin_dir / "codex"
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                'if [ "$1" = "login" ] && [ "$2" = "status" ]; then',
                "  exit 0",
                "fi",
                'actual="$1 $2 $3 $4"',
                'expected="--dangerously-bypass-approvals-and-sandbox exec"',
                'expected="$expected --ephemeral --skip-git-repo-check"',
                'if [ "$actual" = "$expected" ]; then',
                '  printf "Codex planning guidance\\n"',
                "  exit 0",
                "fi",
                'printf "unexpected codex args: %s\\n" "$*" >&2',
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    codex_bin.chmod(0o755)
    return codex_bin
