from __future__ import annotations

import os

import pytest

from aiu.config import ProviderName
from aiu.providers import GenerationRequest, OpenAICompatibleProvider


@pytest.mark.skipif(
    os.environ.get("AIU_RUN_OPENAI_INTEGRATION") != "1",
    reason="OpenAI-compatible integration test is opt-in.",
)
def test_openai_provider_small_generation() -> None:
    provider = OpenAICompatibleProvider(ProviderName.OPENAI, "OPENAI_API_KEY")
    result = provider.generate(
        GenerationRequest(
            prompt="Write a one sentence course title for a testing course.",
            purpose="integration",
            max_retries=1,
        )
    )

    assert result.text.strip()
