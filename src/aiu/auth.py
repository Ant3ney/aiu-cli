"""Authentication configuration storage for provider adapters."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aiu.artifact_store import ArtifactStore
from aiu.config import ProviderConfig, ProviderName


class AuthConfigurationError(ValueError):
    """Raised when provider auth configuration is invalid."""


class AuthConfigFile(BaseModel):
    """Persisted provider auth configuration."""

    model_config = ConfigDict(extra="forbid")

    providers: dict[ProviderName, ProviderConfig] = Field(default_factory=dict)


class AuthStore:
    """Read and write auth configuration without persisting raw secrets."""

    def __init__(self, config_home: str | Path | None = None) -> None:
        self.config_home = Path(config_home) if config_home is not None else default_config_home()
        self.path = self.config_home / "auth.json"

    def load(self) -> AuthConfigFile:
        if not self.path.exists():
            return AuthConfigFile()
        return AuthConfigFile.model_validate(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, config: AuthConfigFile) -> None:
        store = ArtifactStore(self.config_home)
        store.write_json("auth.json", config)

    def configure_provider(
        self,
        provider: ProviderName,
        api_key_env: str | None = None,
        codex_command: str = "codex",
    ) -> None:
        provider = ProviderName(provider)
        if provider == ProviderName.FAKE:
            normalized = ProviderConfig(provider=provider)
        elif provider == ProviderName.CODEX:
            if api_key_env:
                raise AuthConfigurationError(
                    "Codex authentication uses the local Codex CLI and does not accept "
                    "--api-key-env."
                )
            _verify_codex_authenticated(codex_command)
            normalized = ProviderConfig(provider=provider, codex_command=codex_command)
        elif provider == ProviderName.OPENAI:
            if not api_key_env:
                raise AuthConfigurationError(
                    f"--api-key-env is required when configuring provider '{provider.value}'."
                )
            if "=" in api_key_env:
                raise AuthConfigurationError("--api-key-env must be an environment variable name.")
            if api_key_env not in os.environ:
                raise AuthConfigurationError(
                    f"Environment variable is not set for provider '{provider.value}': "
                    f"{api_key_env}"
                )
            normalized = ProviderConfig(provider=provider, api_key_env=api_key_env)
        else:
            raise AuthConfigurationError(f"Unsupported provider: {provider.value}")

        config = self.load()
        config.providers[provider] = normalized
        self.save(config)

    def status_lines(self) -> list[str]:
        config = self.load()
        if not config.providers:
            return ["No providers configured."]

        lines = ["Configured providers:"]
        for provider in sorted(config.providers):
            provider_config = config.providers[provider]
            if provider == ProviderName.FAKE:
                detail = "no authentication required"
            elif provider == ProviderName.CODEX:
                codex_command = provider_config.codex_command or "codex"
                try:
                    _verify_codex_authenticated(codex_command)
                except AuthConfigurationError as exc:
                    detail = f"configured but unavailable: {exc}"
                else:
                    detail = f"authenticated via local Codex CLI ({codex_command})"
            elif provider_config.api_key_env is None:
                detail = "missing API key environment reference"
            else:
                state = "set" if provider_config.api_key_env in os.environ else "missing"
                detail = f"api key env {provider_config.api_key_env} ({state})"
            lines.append(f"- {provider.value}: {detail}")
        return lines


def default_config_home() -> Path:
    """Return the AIU config directory, honoring test/user overrides."""

    if configured_home := os.environ.get("AIU_CONFIG_HOME"):
        return Path(configured_home).expanduser()
    if xdg_config_home := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg_config_home).expanduser() / "aiu"
    return Path.home() / ".config" / "aiu"


def _verify_codex_authenticated(codex_command: str) -> None:
    """Ensure a local Codex CLI is installed and logged in."""

    try:
        result = subprocess.run(
            [codex_command, "login", "status"],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AuthConfigurationError(
            "Codex CLI was not found. Install Codex, make sure it is on PATH, "
            "then run `codex login`."
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        message = "Codex CLI is not authenticated. Run `codex login` and try again."
        if detail:
            message = f"{message} Codex reported: {detail}"
        raise AuthConfigurationError(message)
