"""Provider adapter interfaces and deterministic local providers."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from aiu.config import ProviderName


class ProviderError(RuntimeError):
    """Base provider adapter error."""


class ProviderUnavailableError(ProviderError):
    """Raised when a provider exists but cannot service a request yet."""


class ProviderAuthenticationError(ProviderError):
    """Raised when provider credentials are missing or rejected."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider reports a retryable rate-limit condition."""


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider feature metadata used by planning and generation."""

    provider: ProviderName
    supports_streaming: bool
    supports_usage: bool
    supports_retries: bool
    deterministic: bool = False


@dataclass(frozen=True)
class ProviderUsage:
    """Minimal usage accounting for generated content."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class GenerationRequest:
    """Provider generation request."""

    prompt: str
    purpose: str = "general"
    system_prompt: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    max_retries: int = 2


@dataclass(frozen=True)
class GenerationResult:
    """Provider generation response."""

    text: str
    provider: ProviderName
    usage: ProviderUsage
    metadata: dict[str, str] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """Common adapter contract for local, fake, and remote model providers."""

    @property
    def name(self) -> ProviderName:
        """Provider identifier."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Feature and retry metadata."""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a complete response."""

    def stream(self, request: GenerationRequest) -> Iterable[str]:
        """Optionally stream progress chunks."""


class FakeProvider:
    """Deterministic provider used for local tests and dry runs."""

    @property
    def name(self) -> ProviderName:
        return ProviderName.FAKE

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=ProviderName.FAKE,
            supports_streaming=True,
            supports_usage=True,
            supports_retries=True,
            deterministic=True,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        compact_prompt = " ".join(request.prompt.split())
        text = f"[fake:{request.purpose}] {compact_prompt}"
        usage = ProviderUsage(
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(text.split()),
            total_tokens=len(request.prompt.split()) + len(text.split()),
        )
        return GenerationResult(
            text=text,
            provider=ProviderName.FAKE,
            usage=usage,
            metadata={"purpose": request.purpose},
        )

    def stream(self, request: GenerationRequest) -> Iterable[str]:
        result = self.generate(request)
        yield result.text


class CodexProvider:
    """Provider adapter that delegates generation to the local Codex CLI."""

    def __init__(self, codex_command: str = "codex") -> None:
        self.codex_command = codex_command

    @property
    def name(self) -> ProviderName:
        return ProviderName.CODEX

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=ProviderName.CODEX,
            supports_streaming=False,
            supports_usage=False,
            supports_retries=True,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        prompt = _codex_prompt_for_request(request)
        try:
            result = subprocess.run(
                [
                    self.codex_command,
                    "--dangerously-bypass-approvals-and-sandbox",
                    "exec",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    prompt,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ProviderAuthenticationError(
                "Codex CLI was not found. Install Codex, run `codex login`, "
                "then configure AIU with `aiu auth login --provider codex`."
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            message = "Codex provider failed. Confirm `codex login status` succeeds."
            if detail:
                message = f"{message} Codex reported: {detail}"
            raise ProviderUnavailableError(message)

        text = result.stdout.strip()
        return GenerationResult(
            text=text,
            provider=ProviderName.CODEX,
            usage=ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            metadata={"purpose": request.purpose, "codex_command": self.codex_command},
        )

    def stream(self, request: GenerationRequest) -> Iterable[str]:
        yield self.generate(request).text


class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions provider adapter."""

    def __init__(self, provider: ProviderName, api_key_env: str) -> None:
        self._provider = provider
        self.api_key_env = api_key_env

    @property
    def name(self) -> ProviderName:
        return self._provider

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self._provider,
            supports_streaming=False,
            supports_usage=True,
            supports_retries=True,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderAuthenticationError(
                f"Environment variable for provider '{self._provider.value}' is not set: "
                f"{self.api_key_env}"
            )

        payload = {
            "messages": _messages_for_request(request),
            "model": os.environ.get("AIU_OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0.2,
        }
        response = self._post_with_retries(
            payload, api_key=api_key, max_retries=request.max_retries
        )
        text = str(response["choices"][0]["message"]["content"])
        usage_payload = response.get("usage", {})
        usage = ProviderUsage(
            prompt_tokens=int(usage_payload.get("prompt_tokens", 0)),
            completion_tokens=int(usage_payload.get("completion_tokens", 0)),
            total_tokens=int(usage_payload.get("total_tokens", 0)),
        )
        return GenerationResult(
            text=text,
            provider=self._provider,
            usage=usage,
            metadata={
                "model": str(response.get("model", payload["model"])),
                "purpose": request.purpose,
                "response_id": str(response.get("id", "")),
            },
        )

    def stream(self, request: GenerationRequest) -> Iterable[str]:
        yield self.generate(request).text

    def _post_with_retries(
        self,
        payload: dict[str, object],
        *,
        api_key: str,
        max_retries: int,
    ) -> dict[str, object]:
        attempts = max(1, max_retries + 1)
        last_error: ProviderError | None = None
        for attempt in range(attempts):
            try:
                return self._post_json(payload, api_key=api_key)
            except ProviderRateLimitError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                time.sleep(min(2**attempt, 8) * 0.1)
        if last_error is not None:
            raise last_error
        raise ProviderUnavailableError("Provider request failed without a response.")

    def _post_json(self, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        base_url = os.environ.get("AIU_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderAuthenticationError(
                    f"Provider '{self._provider.value}' rejected the configured credentials."
                ) from exc
            if exc.code in {429, 500, 502, 503, 504}:
                raise ProviderRateLimitError(
                    f"Provider '{self._provider.value}' request is retryable: HTTP {exc.code}."
                ) from exc
            raise ProviderUnavailableError(
                f"Provider '{self._provider.value}' request failed: HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderRateLimitError(
                f"Provider '{self._provider.value}' request failed with a retryable network error."
            ) from exc


def provider_for_name(
    provider: ProviderName,
    api_key_env: str | None = None,
    codex_command: str | None = None,
) -> ProviderAdapter:
    """Build a provider adapter from config."""

    provider = ProviderName(provider)
    if provider == ProviderName.FAKE:
        return FakeProvider()
    if provider == ProviderName.CODEX:
        return CodexProvider(codex_command or "codex")
    if api_key_env is None:
        raise ProviderUnavailableError(
            f"Provider '{provider.value}' requires an API key environment variable."
        )
    return OpenAICompatibleProvider(provider, api_key_env)


def _messages_for_request(request: GenerationRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.prompt})
    return messages


def _codex_prompt_for_request(request: GenerationRequest) -> str:
    parts: list[str] = []
    if request.system_prompt:
        parts.append(request.system_prompt)
    parts.append(request.prompt)
    return "\n\n".join(parts)
