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


def planned_course(tmp_path: Path) -> Path:
    course_root = tmp_path / "course"
    create = run_aiu(
        "course",
        "create",
        "Teach me databases",
        "--provider",
        "fake",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )
    plan = run_aiu("course", "plan", str(course_root), cwd=tmp_path)
    assert create.returncode == 0, create.stderr
    assert plan.returncode == 0, plan.stderr
    return course_root


def test_generate_refuses_without_approval(tmp_path: Path) -> None:
    course_root = planned_course(tmp_path)

    result = run_aiu("course", "generate", str(course_root), cwd=tmp_path)

    assert result.returncode != 0
    assert "Course blueprint must be approved" in result.stderr


def test_approve_writes_snapshot_and_allows_dry_run_generation(tmp_path: Path) -> None:
    course_root = planned_course(tmp_path)

    approve = run_aiu("course", "approve", str(course_root), cwd=tmp_path)
    generate = run_aiu("course", "generate", str(course_root), "--dry-run", cwd=tmp_path)

    assert approve.returncode == 0, approve.stderr
    assert generate.returncode == 0, generate.stderr
    assert (course_root / "approved_course_blueprint.json").is_file()
    assert (course_root / "approval_metadata.json").is_file()

    blueprint = json.loads((course_root / "course_blueprint.json").read_text(encoding="utf-8"))
    approved = json.loads(
        (course_root / "approved_course_blueprint.json").read_text(encoding="utf-8")
    )
    assert approved == blueprint


def test_generate_yes_approves_and_dry_runs(tmp_path: Path) -> None:
    course_root = planned_course(tmp_path)

    result = run_aiu("course", "generate", str(course_root), "--yes", "--dry-run", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Generation dry run ready" in result.stdout
    metadata = json.loads((course_root / "approval_metadata.json").read_text(encoding="utf-8"))
    assert metadata["approval_mode"] == "auto"


def test_reapproval_refreshes_metadata_without_changing_blueprint_snapshot(tmp_path: Path) -> None:
    course_root = planned_course(tmp_path)

    first = run_aiu("course", "approve", str(course_root), cwd=tmp_path)
    first_metadata = json.loads(
        (course_root / "approval_metadata.json").read_text(encoding="utf-8")
    )
    second = run_aiu("course", "approve", str(course_root), cwd=tmp_path)
    second_metadata = json.loads(
        (course_root / "approval_metadata.json").read_text(encoding="utf-8")
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_metadata["blueprint_checksum"] == second_metadata["blueprint_checksum"]
    assert first_metadata["approved_blueprint_ref"] == second_metadata["approved_blueprint_ref"]
