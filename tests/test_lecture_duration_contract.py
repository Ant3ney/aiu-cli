from __future__ import annotations

from pathlib import Path

from aiu.config import CourseSettings
from aiu.lecture_quality import (
    DEFAULT_LECTURE_HOURS,
    DEFAULT_LECTURE_MINIMUM_WORDS,
    WORDS_PER_SPOKEN_MINUTE,
    minimum_transcript_words,
)


def test_default_lecture_duration_requires_two_hours_of_spoken_words() -> None:
    assert CourseSettings().lecture_hours == DEFAULT_LECTURE_HOURS
    assert WORDS_PER_SPOKEN_MINUTE == 150
    assert DEFAULT_LECTURE_MINIMUM_WORDS == 18_000
    assert minimum_transcript_words(DEFAULT_LECTURE_HOURS) == 18_000


def test_docs_lock_default_two_hour_lecture_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")

    for text in (readme, agents):
        assert "two hours" in text
        assert "18,000" in text
        assert "150 spoken words" in text
