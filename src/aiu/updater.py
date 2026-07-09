"""Self-update support for the AI University CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPOSITORY_URL = "https://github.com/Ant3ney/aiu-cli.git"
ENV_SOURCE_DIR = "AIU_UPDATE_SOURCE_DIR"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class UpdateError(ValueError):
    """Raised when the CLI cannot update itself."""


@dataclass(frozen=True)
class UpdateCommand:
    """A command executed or planned during update."""

    args: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class UpdateResult:
    """Summary of an update run."""

    commands: tuple[UpdateCommand, ...]
    dry_run: bool
    source_dir: Path


def update_aiu(
    *,
    branch: str | None = None,
    dry_run: bool = False,
    package_file: Path | None = None,
    python_executable: str | None = None,
    repo_url: str = DEFAULT_REPOSITORY_URL,
    runner: Runner = subprocess.run,
    source_dir: str | Path | None = None,
) -> UpdateResult:
    """Pull the AIU source checkout and reinstall it with the active Python."""

    package_file = package_file or Path(__file__)
    python_executable = python_executable or sys.executable
    checkout = _source_checkout(package_file=package_file, source_dir=source_dir)
    commands: list[UpdateCommand] = []

    if checkout.exists() and not _is_git_checkout(checkout):
        raise UpdateError(
            f"Update source directory exists but is not a git checkout: {checkout}"
        )

    if not checkout.exists():
        _run(
            ["git", "clone", repo_url, str(checkout)],
            cwd=checkout.parent,
            commands=commands,
            dry_run=dry_run,
            runner=runner,
        )
    elif branch is None:
        _run(
            ["git", "pull", "--ff-only"],
            cwd=checkout,
            commands=commands,
            dry_run=dry_run,
            runner=runner,
        )
    else:
        _run(
            ["git", "fetch", "origin", branch],
            cwd=checkout,
            commands=commands,
            dry_run=dry_run,
            runner=runner,
        )
        _run(
            ["git", "checkout", branch],
            cwd=checkout,
            commands=commands,
            dry_run=dry_run,
            runner=runner,
        )
        _run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=checkout,
            commands=commands,
            dry_run=dry_run,
            runner=runner,
        )

    _run(
        [python_executable, "-m", "pip", "install", "--upgrade", str(checkout)],
        cwd=checkout,
        commands=commands,
        dry_run=dry_run,
        runner=runner,
    )
    return UpdateResult(commands=tuple(commands), dry_run=dry_run, source_dir=checkout)


def _source_checkout(*, package_file: Path, source_dir: str | Path | None) -> Path:
    if source_dir is not None:
        return Path(source_dir).expanduser().resolve(strict=False)

    env_source_dir = os.environ.get(ENV_SOURCE_DIR)
    if env_source_dir:
        return Path(env_source_dir).expanduser().resolve(strict=False)

    package_git_root = _find_git_root(package_file.resolve(strict=False))
    if package_git_root is not None:
        return package_git_root

    managed_checkout = _managed_source_dir()
    if managed_checkout.exists():
        return managed_checkout
    return managed_checkout


def _managed_source_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        root = Path(data_home).expanduser()
    else:
        root = Path.home() / ".local" / "share"
    return (root / "aiu-cli" / "source").resolve(strict=False)


def _find_git_root(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if _is_git_checkout(candidate):
            return candidate
    return None


def _is_git_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def _run(
    args: Sequence[str],
    *,
    commands: list[UpdateCommand],
    cwd: Path,
    dry_run: bool,
    runner: Runner,
) -> None:
    command = UpdateCommand(args=tuple(args), cwd=cwd)
    commands.append(command)
    if dry_run:
        return

    cwd.mkdir(parents=True, exist_ok=True)
    completed = runner(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            detail = f"\n{detail}"
        raise UpdateError(f"Update command failed: {' '.join(args)}{detail}")
