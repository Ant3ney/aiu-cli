from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from aiu.version import __version__


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


def test_help_shows_top_level_command_groups(tmp_path: Path) -> None:
    result = run_aiu("--help", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert "Commands:" in result.stdout
    assert "init" in result.stdout
    assert "auth" in result.stdout
    assert "course" in result.stdout
    assert "update" in result.stdout


def test_version_exits_zero(tmp_path: Path) -> None:
    result = run_aiu("--version", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def test_help_and_version_do_not_create_project_files(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())

    help_result = run_aiu("--help", cwd=tmp_path)
    version_result = run_aiu("--version", cwd=tmp_path)

    after = set(tmp_path.iterdir())
    assert help_result.returncode == 0, help_result.stderr
    assert version_result.returncode == 0, version_result.stderr
    assert after == before


def test_update_dry_run_uses_explicit_source_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "aiu-source"
    source_dir.mkdir()
    (source_dir / ".git").mkdir()
    caller = tmp_path / "caller"
    caller.mkdir()

    result = run_aiu(
        "update",
        "--dry-run",
        "--source-dir",
        str(source_dir),
        cwd=caller,
    )

    assert result.returncode == 0, result.stderr
    assert "Planned update" in result.stdout
    assert f"cd {source_dir}" in result.stdout
    assert f"pip install --upgrade {source_dir}" in result.stdout
    assert f"cd {caller}" not in result.stdout
