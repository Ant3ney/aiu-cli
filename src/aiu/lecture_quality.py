"""Lecture transcript quality helpers."""

from __future__ import annotations

import math
import re

WORDS_PER_SPOKEN_MINUTE = 150

_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def minimum_transcript_words(duration_hours: float) -> int:
    """Return the minimum spoken-transcript word count for a lecture duration."""

    minutes = max(0.0, duration_hours) * 60
    return max(1, math.ceil(minutes * WORDS_PER_SPOKEN_MINUTE))


def transcript_word_count(text: str) -> int:
    """Count words in transcript prose using the validation/generation rule."""

    return len(_WORD_PATTERN.findall(text))
