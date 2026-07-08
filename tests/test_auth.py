from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_aiu(
    *args: str, cwd: Path, env: dict[str, str] | None = None
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


def test_auth_login_fake_and_status_do_not_print_secrets(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    result = run_aiu(
        "auth",
        "login",
        "--provider",
        "fake",
        cwd=tmp_path,
        env={"AIU_CONFIG_HOME": str(config_home)},
    )
    status = run_aiu("auth", "status", cwd=tmp_path, env={"AIU_CONFIG_HOME": str(config_home)})

    assert result.returncode == 0, result.stderr
    assert status.returncode == 0, status.stderr
    assert "- fake: no authentication required" in status.stdout

    config = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert config["providers"]["fake"]["provider"] == "fake"
    assert config["providers"]["fake"]["api_key_env"] is None
    assert config["providers"]["fake"]["codex_command"] is None


def test_auth_login_codex_uses_local_codex_without_api_key(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    codex_bin = write_fake_codex(tmp_path, login_status=0)
    env = {
        "AIU_CONFIG_HOME": str(config_home),
        "PATH": f"{codex_bin.parent}:{os.environ['PATH']}",
    }

    result = run_aiu("auth", "login", "--provider", "codex", cwd=tmp_path, env=env)
    status = run_aiu("auth", "status", cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stderr
    assert status.returncode == 0, status.stderr
    assert "authenticated via local Codex CLI" in status.stdout
    config = json.loads((config_home / "auth.json").read_text(encoding="utf-8"))
    assert config["providers"]["codex"] == {
        "api_key_env": None,
        "codex_command": "codex",
        "provider": "codex",
    }


def test_auth_login_codex_rejects_api_key_env(tmp_path: Path) -> None:
    codex_bin = write_fake_codex(tmp_path, login_status=0)
    env = {
        "AIU_CONFIG_HOME": str(tmp_path / "config"),
        "PATH": f"{codex_bin.parent}:{os.environ['PATH']}",
        "OPENAI_API_KEY": "secret",
    }

    result = run_aiu(
        "auth",
        "login",
        "--provider",
        "codex",
        "--api-key-env",
        "OPENAI_API_KEY",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode != 0
    assert "does not accept --api-key-env" in result.stderr


def test_auth_login_codex_requires_local_codex_login(tmp_path: Path) -> None:
    codex_bin = write_fake_codex(tmp_path, login_status=1)
    env = {
        "AIU_CONFIG_HOME": str(tmp_path / "config"),
        "PATH": f"{codex_bin.parent}:{os.environ['PATH']}",
    }

    result = run_aiu("auth", "login", "--provider", "codex", cwd=tmp_path, env=env)

    assert result.returncode != 0
    assert "Codex CLI is not authenticated" in result.stderr


def test_auth_login_openai_stores_env_reference_not_secret(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    secret_value = "super-secret-test-key"
    env = {
        "AIU_CONFIG_HOME": str(config_home),
        "OPENAI_API_KEY": secret_value,
    }

    result = run_aiu(
        "auth",
        "login",
        "--provider",
        "openai",
        "--api-key-env",
        "OPENAI_API_KEY",
        cwd=tmp_path,
        env=env,
    )
    status = run_aiu("auth", "status", cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stderr
    assert status.returncode == 0, status.stderr
    assert "OPENAI_API_KEY" in status.stdout
    assert secret_value not in status.stdout

    raw_config = (config_home / "auth.json").read_text(encoding="utf-8")
    config = json.loads(raw_config)
    assert "OPENAI_API_KEY" in raw_config
    assert secret_value not in raw_config
    assert "codex" not in config["providers"]
    assert config["providers"]["openai"]["codex_command"] is None


def test_auth_login_openai_requires_env_var_to_be_set(tmp_path: Path) -> None:
    result = run_aiu(
        "auth",
        "login",
        "--provider",
        "openai",
        "--api-key-env",
        "MISSING_OPENAI_API_KEY",
        cwd=tmp_path,
        env={"AIU_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.returncode != 0
    assert "Environment variable is not set" in result.stderr
    assert "MISSING_OPENAI_API_KEY" in result.stderr


def write_fake_codex(tmp_path: Path, *, login_status: int) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex_bin = bin_dir / "codex"
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                'if [ "$1" = "login" ] && [ "$2" = "status" ]; then',
                f"  exit {login_status}",
                "fi",
                'if [ "$1" = "exec" ]; then',
                '  printf "fake codex output\\n"',
                "  exit 0",
                "fi",
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    codex_bin.chmod(0o755)
    return codex_bin
