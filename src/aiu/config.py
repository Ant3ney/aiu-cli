"""Typed configuration models for AI University."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProviderName(StrEnum):
    """Supported provider identifiers."""

    FAKE = "fake"
    CODEX = "codex"
    OPENAI = "openai"


class LabPolicy(StrEnum):
    """How the engine should decide whether to include labs."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class CourseSettings(BaseModel):
    """User-editable defaults for a course generation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weeks: int = Field(default=24, ge=1)
    lectures_per_week: int = Field(default=2, ge=1)
    lecture_hours: float = Field(default=2.0, gt=0)
    lab_policy: LabPolicy = LabPolicy.AUTO
    level: str = Field(default="beginner", min_length=1)
    provider: ProviderName = ProviderName.FAKE


class ProviderConfig(BaseModel):
    """Provider configuration that stores references to secrets, never raw secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    api_key_env: str | None = Field(
        default=None,
        description="Name of the environment variable containing the API key.",
    )
