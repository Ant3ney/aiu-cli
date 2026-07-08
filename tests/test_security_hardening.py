from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from aiu.artifact_store import ArtifactStore


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


def test_generated_course_artifacts_do_not_leak_openai_secret(tmp_path: Path) -> None:
    secret = "task20-secret-value"
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me secure systems",
        "--provider",
        "openai",
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
        env={"OPENAI_API_KEY": secret},
    )

    assert result.returncode == 0, result.stderr
    generated_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in course_root.rglob("*")
        if path.is_file()
    )
    assert secret not in generated_text


def test_artifact_store_rejects_cross_platform_path_traversal(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    assert store.course_path("lectures\\week_01\\day_01.md") == (
        tmp_path / "lectures" / "week_01" / "day_01.md"
    )
    for unsafe in ("../outside.json", "lectures/../../outside.json", "/tmp/outside.json"):
        try:
            store.course_path(unsafe)
        except ValueError:
            continue
        raise AssertionError(f"Expected path to be rejected: {unsafe}")


def test_help_commands_for_release_workflows(tmp_path: Path) -> None:
    for args in (
        ("--help",),
        ("course", "create", "--help"),
        ("course", "validate", "--help"),
        ("auth", "--help"),
    ):
        result = run_aiu(*args, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "Usage:" in result.stdout


def test_readme_documents_global_install_and_independent_auth_paths() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install ." in readme
    assert "aiu auth login --provider codex" in readme
    assert "aiu auth login --provider openai --api-key-env OPENAI_API_KEY" in readme
    assert "No OpenAI API key is required" in readme
    assert "Codex install or login is required" in readme
