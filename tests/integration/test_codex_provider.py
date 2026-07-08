from __future__ import annotations

import os
import subprocess

import pytest

from aiu.providers import CodexProvider, GenerationRequest


@pytest.mark.skipif(
    os.environ.get("AIU_RUN_CODEX_INTEGRATION") != "1",
    reason="Codex integration test is opt-in.",
)
def test_codex_provider_small_generation() -> None:
    status = subprocess.run(
        ["codex", "login", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr

    result = CodexProvider().generate(
        GenerationRequest(
            prompt="Write one short sentence about planning a university course.",
            purpose="integration",
        )
    )

    assert result.text.strip()
