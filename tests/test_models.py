from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiu.config import CourseSettings
from aiu.models import (
    ArtifactIndexEntry,
    Assessment,
    AssessmentPlanEntry,
    AssessmentType,
    CourseBlueprint,
    CourseManifest,
    CourseModule,
    LabSession,
    LectureSession,
    SourceManifest,
    ValidationCheck,
    ValidationReport,
    ValidationStatus,
    VRHandoffCue,
    WeekPlan,
)


def test_course_manifest_validates_required_fields_and_portable_paths() -> None:
    manifest = CourseManifest(
        course_id="course_123",
        title="Example",
        version="0.1.0",
        prompt_ref="prompt.md",
        settings=CourseSettings(),
        created_at="2026-07-08T10:00:00Z",
        provider="fake",
        artifact_index=[
            ArtifactIndexEntry(
                artifact_id="syllabus",
                kind="markdown",
                path="syllabus/syllabus.md",
            )
        ],
    )

    assert manifest.artifact_index[0].path == "syllabus/syllabus.md"

    with pytest.raises(ValidationError):
        CourseManifest(
            course_id="course_123",
            title="Example",
            version="0.1.0",
            prompt_ref="/absolute/prompt.md",
            settings=CourseSettings(),
            created_at="2026-07-08T10:00:00Z",
            provider="fake",
        )


def test_core_artifact_models_reject_invalid_data() -> None:
    cue = VRHandoffCue(
        cue_id="cue_1",
        artifact_id="lecture_w01_d01",
        timestamp_or_segment="00:00",
        scene_type="classroom",
        professor_action="introduce the topic",
        visual_aid="board",
        interaction_anchor="opening_question",
    )
    lecture = LectureSession(
        lecture_id="lecture_w01_d01",
        week=1,
        day=1,
        title="Foundations",
        objectives=["Define the field"],
        transcript="Welcome to the course.",
        source_refs=[],
        estimated_duration=2.0,
        vr_cues=[cue],
    )
    lab = LabSession(
        lab_id="lab_w01",
        week=1,
        title="Hands-on setup",
        goals=["Set up the environment"],
        setup="Install the tools.",
        steps=["Open the starter project."],
        expected_outputs=["A working local setup."],
        rubric="Complete/incomplete.",
    )
    assessment = Assessment(
        assessment_id="quiz_w01",
        type=AssessmentType.QUIZ,
        objectives=["Define the field"],
        prompt="Answer the questions.",
        questions=["What is the main idea?"],
        answer_key="The main idea is structured learning.",
        rubric="One point for a clear answer.",
        due_week=1,
    )
    source = SourceManifest(
        source_id="source_1",
        path_or_url="notes/topic.md",
        type="markdown",
        checksum="sha256:abc",
        extraction_status="extracted",
        chunks=["chunk_1"],
        citation_label="notes/topic.md",
    )

    assert lecture.vr_cues[0].cue_id == "cue_1"
    assert lab.steps
    assert assessment.type == AssessmentType.QUIZ
    assert source.extraction_status == "extracted"

    with pytest.raises(ValidationError):
        LectureSession(
            lecture_id="lecture_w01_d01",
            week=0,
            day=1,
            title="Foundations",
            objectives=[],
            transcript="Welcome to the course.",
            estimated_duration=0,
        )


def test_blueprint_and_validation_report_models() -> None:
    blueprint = CourseBlueprint(
        course_title="Example Course",
        description="A focused course.",
        target_learner="beginner",
        outcomes=["Explain the fundamentals"],
        prerequisites=[],
        modules=[
            CourseModule(
                module_id="module_1",
                title="Foundations",
                weeks=[1],
                objectives=["Explain the fundamentals"],
                rationale="Start with core ideas.",
            )
        ],
        week_plan=[
            WeekPlan(
                week=1,
                title="Foundations",
                topics=["Core terms"],
                lecture_titles=["Introduction"],
            )
        ],
        assessment_plan=[
            AssessmentPlanEntry(
                assessment_id="quiz_w01",
                type="quiz",
                due_week=1,
                objectives=["Explain the fundamentals"],
                description="Short diagnostic quiz.",
            )
        ],
        lab_policy="auto",
    )
    report = ValidationReport(
        status=ValidationStatus.WARN,
        checks=[
            ValidationCheck(
                check_id="schedule",
                status=ValidationStatus.PASS,
                message="Schedule exists.",
            )
        ],
        warnings=["No external citations."],
        failures=[],
        artifact_counts={"lectures": 0},
        citation_coverage=0.0,
        schema_errors=[],
    )

    assert blueprint.course_title == "Example Course"
    assert report.status == ValidationStatus.WARN

    with pytest.raises(ValidationError):
        ValidationReport(
            status="pass",
            citation_coverage=1.5,
        )
