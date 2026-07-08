from __future__ import annotations

import pytest

from aiu.config import ProviderName
from aiu.providers import (
    CodexProvider,
    FakeProvider,
    GenerationRequest,
    OpenAICompatibleProvider,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    provider_for_name,
)


def test_fake_provider_is_deterministic_and_tracks_usage() -> None:
    provider = FakeProvider()
    request = GenerationRequest(prompt="Teach me databases", purpose="blueprint")

    first = provider.generate(request)
    second = provider.generate(request)

    assert first == second
    assert first.provider == ProviderName.FAKE
    assert first.text == "[fake:blueprint] Teach me databases"
    assert first.usage.total_tokens == first.usage.prompt_tokens + first.usage.completion_tokens
    assert list(provider.stream(request)) == [first.text]


def test_provider_for_name_requires_secret_reference_for_openai() -> None:
    provider = provider_for_name(ProviderName.FAKE)
    assert provider.name == ProviderName.FAKE
    assert provider_for_name(ProviderName.CODEX).name == ProviderName.CODEX

    with pytest.raises(ProviderUnavailableError):
        provider_for_name(ProviderName.OPENAI)


def test_codex_provider_uses_codex_exec_stdout(tmp_path) -> None:
    codex_bin = tmp_path / "codex"
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                'actual="$1 $2 $3 $4"',
                'expected="--dangerously-bypass-approvals-and-sandbox exec"',
                'expected="$expected --ephemeral --skip-git-repo-check"',
                'if [ "$actual" = "$expected" ]; then',
                '  printf "Codex generated course guidance\\n"',
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
    provider = CodexProvider(str(codex_bin))

    result = provider.generate(GenerationRequest(prompt="Teach me systems", purpose="plan"))

    assert result.provider == ProviderName.CODEX
    assert result.text == "Codex generated course guidance"
    assert result.usage.total_tokens == 0


def test_codex_provider_failure_is_clear(tmp_path) -> None:
    codex_bin = tmp_path / "codex"
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                'printf "not logged in" >&2',
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    codex_bin.chmod(0o755)
    provider = CodexProvider(str(codex_bin))

    with pytest.raises(ProviderUnavailableError, match="not logged in"):
        provider.generate(GenerationRequest(prompt="Teach me systems"))


def test_openai_compatible_provider_uses_env_secret_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    provider = OpenAICompatibleProvider(ProviderName.OPENAI, "OPENAI_API_KEY")

    def fake_post_json(payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        assert api_key == secret
        assert payload["model"] == "gpt-4o-mini"
        return {
            "id": "response_1",
            "model": "test-model",
            "choices": [{"message": {"content": "Generated blueprint text."}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post_json)
    result = provider.generate(GenerationRequest(prompt="Teach me testing", purpose="blueprint"))

    assert result.text == "Generated blueprint text."
    assert result.usage.total_tokens == 7
    assert secret not in str(result)


def test_openai_compatible_provider_retries_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")
    monkeypatch.setattr("aiu.providers.time.sleep", lambda _seconds: None)
    provider = OpenAICompatibleProvider(ProviderName.OPENAI, "OPENAI_API_KEY")
    attempts = {"count": 0}

    def flaky_post_json(payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProviderRateLimitError("retry")
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(provider, "_post_json", flaky_post_json)
    result = provider.generate(GenerationRequest(prompt="hello", max_retries=1))

    assert result.text == "ok"
    assert attempts["count"] == 2


def test_openai_compatible_provider_requires_configured_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAICompatibleProvider(ProviderName.OPENAI, "OPENAI_API_KEY")

    with pytest.raises(ProviderAuthenticationError):
        provider.generate(GenerationRequest(prompt="hello"))
