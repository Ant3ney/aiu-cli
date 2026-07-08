"""Prompt intake helpers for course creation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TextIO


class PromptIntakeError(ValueError):
    """Raised when prompt input is missing, ambiguous, or unreadable."""


def read_prompt_text(
    *,
    prompt_text: str | None,
    prompt_file: str | None,
    from_stdin: bool,
    stdin: TextIO,
) -> str:
    """Read prompt text from exactly one supported source."""

    source_count = sum(source is not None for source in (prompt_text, prompt_file)) + int(
        from_stdin
    )
    if source_count != 1:
        raise PromptIntakeError("Use exactly one prompt source: argument, --prompt, or --stdin.")

    if prompt_text is not None:
        text = prompt_text
    elif prompt_file is not None:
        try:
            text = Path(prompt_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptIntakeError(f"Unable to read prompt file: {prompt_file}") from exc
    else:
        text = stdin.read()

    if not text.strip():
        raise PromptIntakeError("Prompt text cannot be empty.")

    return text


def prompt_sha256(prompt_text: str) -> str:
    """Return the manifest checksum for prompt text."""

    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
