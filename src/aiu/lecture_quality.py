"""Lecture transcript quality helpers."""

from __future__ import annotations

import math
import re

WORDS_PER_SPOKEN_MINUTE = 150
DEFAULT_LECTURE_HOURS = 2.0
DEFAULT_LECTURE_MINIMUM_WORDS = 18_000

_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def minimum_transcript_words(duration_hours: float) -> int:
    """Return the minimum spoken-transcript word count for a lecture duration.

    The default AIU lecture contract is two hours of professor speech, which is
    18,000 words at 150 spoken words per minute. Do not lower this invariant
    without an explicit product decision.
    """

    minutes = max(0.0, duration_hours) * 60
    return max(1, math.ceil(minutes * WORDS_PER_SPOKEN_MINUTE))


def transcript_word_count(text: str) -> int:
    """Count words in transcript prose using the validation/generation rule."""

    return len(_WORD_PATTERN.findall(text))
