from __future__ import annotations

from pathlib import Path

from aiu.updater import DEFAULT_REPOSITORY_URL, update_aiu


def test_update_uses_package_checkout_not_invocation_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    caller_repo = tmp_path / "caller"
    caller_repo.mkdir()
    (caller_repo / ".git").mkdir()
    source_repo = tmp_path / "aiu-source"
    package_file = source_repo / "src" / "aiu" / "updater.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    (source_repo / ".git").mkdir()
    monkeypatch.chdir(caller_repo)

    result = update_aiu(
        dry_run=True,
        package_file=package_file,
        python_executable="/opt/aiu/bin/python",
    )

    assert result.source_dir == source_repo
    assert all(command.cwd != caller_repo for command in result.commands)
    assert result.commands[0].args == ("git", "pull", "--ff-only")
    assert result.commands[0].cwd == source_repo
    assert result.commands[-1].args == (
        "/opt/aiu/bin/python",
        "-m",
        "pip",
        "install",
        "--upgrade",
        str(source_repo),
    )
    assert result.commands[-1].cwd == source_repo


def test_update_clones_to_managed_source_when_package_has_no_git_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_home = tmp_path / "data"
    package_file = tmp_path / "site-packages" / "aiu" / "updater.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    result = update_aiu(
        dry_run=True,
        package_file=package_file,
        python_executable="/opt/aiu/bin/python",
    )

    expected_source = data_home / "aiu-cli" / "source"
    assert result.source_dir == expected_source
    assert not expected_source.parent.exists()
    assert result.commands[0].args == (
        "git",
        "clone",
        DEFAULT_REPOSITORY_URL,
        str(expected_source),
    )
    assert result.commands[0].cwd == expected_source.parent
    assert result.commands[-1].args == (
        "/opt/aiu/bin/python",
        "-m",
        "pip",
        "install",
        "--upgrade",
        str(expected_source),
    )


def test_update_env_source_dir_overrides_package_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_repo = tmp_path / "package-repo"
    package_file = package_repo / "src" / "aiu" / "updater.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    (package_repo / ".git").mkdir()
    override_repo = tmp_path / "override-repo"
    override_repo.mkdir()
    (override_repo / ".git").mkdir()
    monkeypatch.setenv("AIU_UPDATE_SOURCE_DIR", str(override_repo))

    result = update_aiu(
        dry_run=True,
        package_file=package_file,
        python_executable="/opt/aiu/bin/python",
    )

    assert result.source_dir == override_repo
    assert result.commands[0].cwd == override_repo
