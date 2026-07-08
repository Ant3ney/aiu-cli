"""Core typed data models for AI University artifacts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aiu.config import CourseSettings, LabPolicy, ProviderName


class ValidationStatus(StrEnum):
    """Validation report outcomes."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ExtractionStatus(StrEnum):
    """Source extraction lifecycle values."""

    PENDING = "pending"
    EXTRACTED = "extracted"
    SKIPPED = "skipped"
    FAILED = "failed"


class AssessmentType(StrEnum):
    """Supported academic assessment categories."""

    HOMEWORK = "homework"
    QUIZ = "quiz"
    PROJECT = "project"
    MIDTERM = "midterm"
    FINAL = "final"
    ACTIVITY = "activity"


class AIUModel(BaseModel):
    """Base model settings shared by persisted schemas."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def portable_relative_path(path: str) -> str:
    """Normalize and validate a manifest path for portable JSON output."""

    normalized = path.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("path cannot be empty")
    if normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
        raise ValueError("path must be relative to the course root")
    if "/../" in normalized or normalized.endswith("/.."):
        raise ValueError("path cannot traverse outside the course root")
    return normalized


class ArtifactIndexEntry(AIUModel):
    """Manifest entry for a generated or user-provided artifact."""

    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _path_is_portable(cls, value: str) -> str:
        return portable_relative_path(value)


class CourseManifest(AIUModel):
    """Top-level metadata for a generated course package."""

    course_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompt_ref: str | None
    settings: CourseSettings
    created_at: str = Field(min_length=1)
    provider: ProviderName
    artifact_index: list[ArtifactIndexEntry] = Field(default_factory=list)
    course_config_ref: str = "course.yaml"
    prompt_checksum: str | None = None

    @field_validator("prompt_ref", "course_config_ref")
    @classmethod
    def _refs_are_portable(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return portable_relative_path(value)


class SourceManifest(AIUModel):
    """Inventory record for a user-provided or researched source."""

    source_id: str = Field(min_length=1)
    path_or_url: str = Field(min_length=1)
    type: str = Field(min_length=1)
    checksum: str | None = None
    extraction_status: ExtractionStatus
    chunks: list[str] = Field(default_factory=list)
    citation_label: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, ge=0)
    errors: list[str] = Field(default_factory=list)


class SourceManifestIndex(AIUModel):
    """Container for a complete source manifest file."""

    sources: list[SourceManifest] = Field(default_factory=list)


class WeekPlan(AIUModel):
    """Planned course work for one week."""

    week: int = Field(ge=1)
    title: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    lecture_titles: list[str] = Field(min_length=1)
    lab: str | None = None
    assessments: list[str] = Field(default_factory=list)


class CourseModule(AIUModel):
    """Module-level grouping used in a course blueprint."""

    module_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    weeks: list[int] = Field(min_length=1)
    objectives: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class AssessmentPlanEntry(AIUModel):
    """Planned assessment summary in a course blueprint."""

    assessment_id: str = Field(min_length=1)
    type: AssessmentType
    due_week: int = Field(ge=1)
    objectives: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)


class CourseBlueprint(AIUModel):
    """Approved course plan and dependency anchor."""

    course_title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    target_learner: str = Field(min_length=1)
    outcomes: list[str] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    modules: list[CourseModule] = Field(min_length=1)
    week_plan: list[WeekPlan] = Field(min_length=1)
    assessment_plan: list[AssessmentPlanEntry] = Field(min_length=1)
    lab_policy: LabPolicy
    lab_policy_rationale: str | None = None
    source_usage_plan: list[str] = Field(default_factory=list)


class VRHandoffCue(AIUModel):
    """Future graphics and VR metadata for an artifact segment."""

    cue_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    timestamp_or_segment: str = Field(min_length=1)
    scene_type: str = Field(min_length=1)
    professor_action: str = Field(min_length=1)
    visual_aid: str | None = None
    interaction_anchor: str | None = None


class LectureSession(AIUModel):
    """One lecture transcript and machine-readable metadata."""

    lecture_id: str = Field(min_length=1)
    week: int = Field(ge=1)
    day: int = Field(ge=1)
    title: str = Field(min_length=1)
    objectives: list[str] = Field(min_length=1)
    transcript: str = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    estimated_duration: float = Field(gt=0)
    vr_cues: list[VRHandoffCue] = Field(default_factory=list)


class LabSession(AIUModel):
    """Lab transcript, instructions, and metadata."""

    lab_id: str = Field(min_length=1)
    week: int = Field(ge=1)
    title: str = Field(min_length=1)
    goals: list[str] = Field(min_length=1)
    setup: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    safety_notes: list[str] = Field(default_factory=list)
    rubric: str = Field(min_length=1)
    vr_cues: list[VRHandoffCue] = Field(default_factory=list)


class Assessment(AIUModel):
    """Quiz, homework, project, exam, or activity definition."""

    assessment_id: str = Field(min_length=1)
    type: AssessmentType
    objectives: list[str] = Field(min_length=1)
    prompt: str = Field(min_length=1)
    questions: list[str] = Field(min_length=1)
    answer_key: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    due_week: int = Field(ge=1)


class ValidationCheck(AIUModel):
    """Single validation check result."""

    check_id: str = Field(min_length=1)
    status: ValidationStatus
    message: str = Field(min_length=1)
    artifact_ref: str | None = None


class ValidationReport(AIUModel):
    """Quality and completeness report for a course package."""

    status: ValidationStatus
    checks: list[ValidationCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    citation_coverage: float = Field(ge=0, le=1)
    schema_errors: list[str] = Field(default_factory=list)
