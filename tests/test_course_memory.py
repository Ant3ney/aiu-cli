from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aiu.config import LabPolicy
from aiu.course_memory import (
    build_lecture_context_packet,
    lecture_context_prompt,
    record_lecture_memory,
    write_course_memory,
)
from aiu.models import (
    AssessmentPlanEntry,
    AssessmentType,
    CourseBlueprint,
    CourseModule,
    LectureSession,
    WeekPlan,
)


def run_aiu(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    aiu_executable = Path(sys.executable).with_name("aiu")
    return subprocess.run(
        [str(aiu_executable), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def blueprint() -> CourseBlueprint:
    return CourseBlueprint(
        course_title="Systems Course",
        description="A systems course.",
        target_learner="beginner",
        outcomes=[
            "Explain systems foundations.",
            "Apply systems design.",
        ],
        prerequisites=[],
        modules=[
            CourseModule(
                module_id="module_01",
                title="Systems Foundations",
                weeks=[1, 2],
                objectives=["Explain systems foundations."],
                rationale="Foundations precede applications.",
            )
        ],
        week_plan=[
            WeekPlan(
                week=1,
                title="Week 1",
                topics=["processes", "memory"],
                lecture_titles=["Processes", "Memory"],
                lab="Process lab",
                assessments=["homework_w01"],
            ),
            WeekPlan(
                week=2,
                title="Week 2",
                topics=["scheduling", "coordination"],
                lecture_titles=["Scheduling"],
                lab="Scheduling lab",
                assessments=["homework_w02"],
            ),
        ],
        assessment_plan=[
            AssessmentPlanEntry(
                assessment_id="homework_w01",
                type=AssessmentType.HOMEWORK,
                due_week=1,
                objectives=["Explain systems foundations."],
                description="Week 1 homework.",
            ),
            AssessmentPlanEntry(
                assessment_id="quiz_w02",
                type=AssessmentType.QUIZ,
                due_week=2,
                objectives=["Apply systems design."],
                description="Week 2 quiz.",
            ),
        ],
        lab_policy=LabPolicy.AUTO,
        lab_policy_rationale="Applied practice is useful.",
        source_usage_plan=[],
    )


def test_lecture_context_uses_summaries_not_raw_prior_transcripts(tmp_path: Path) -> None:
    course_blueprint = blueprint()
    raw_transcript = "RAW TRANSCRIPT SHOULD NOT APPEAR " * 20
    record_lecture_memory(
        tmp_path,
        LectureSession(
            lecture_id="lecture_w01_d01",
            week=1,
            day=1,
            title="Processes",
            objectives=["Explain systems foundations."],
            transcript=raw_transcript,
            source_refs=[],
            estimated_duration=2.0,
            vr_cues=[],
        ),
        course_blueprint,
        artifact_ref="lectures/week_01/day_01.md",
    )

    packet = build_lecture_context_packet(
        tmp_path,
        course_blueprint,
        {"id": "lecture_w01_d02", "week": 1, "day": 2, "title": "Memory"},
        ["Apply systems design."],
        source_context="No local source excerpts were available.",
    )
    rendered = lecture_context_prompt(packet)

    assert "Processes covered" in rendered
    assert "RAW TRANSCRIPT SHOULD NOT APPEAR" not in rendered
    assert packet["objectives"] == ["Apply systems design."]
    assert packet["avoid_repeating"]


def test_targeted_regeneration_context_excludes_target_and_later_memory(
    tmp_path: Path,
) -> None:
    course_blueprint = blueprint()
    write_course_memory(
        tmp_path,
        {
            "activities": [],
            "assessments": [],
            "covered_concepts": [],
            "created_at": "2026-07-08T00:00:00Z",
            "lectures": [
                {
                    "day": 1,
                    "lecture_id": "lecture_w01_d01",
                    "summary": "Prior lecture summary.",
                    "week": 1,
                },
                {
                    "day": 2,
                    "lecture_id": "lecture_w01_d02",
                    "summary": "Stale target summary.",
                    "week": 1,
                },
                {
                    "day": 1,
                    "lecture_id": "lecture_w02_d01",
                    "summary": "Later lecture summary.",
                    "week": 2,
                },
            ],
            "open_threads": [],
            "updated_at": "2026-07-08T00:00:00Z",
            "version": 1,
        },
    )

    packet = build_lecture_context_packet(
        tmp_path,
        course_blueprint,
        {"id": "lecture_w01_d02", "week": 1, "day": 2, "title": "Memory"},
        ["Apply systems design."],
        source_context="No local source excerpts were available.",
    )
    rendered = lecture_context_prompt(packet)

    assert "Prior lecture summary" in rendered
    assert "Stale target summary" not in rendered
    assert "Later lecture summary" not in rendered


def test_chronological_generation_updates_memory_before_later_lectures(
    tmp_path: Path,
) -> None:
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me operating systems",
        "--provider",
        "fake",
        "--weeks",
        "2",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    memory = json.loads((course_root / "course_memory.json").read_text(encoding="utf-8"))
    week_two = json.loads(
        (course_root / "lectures" / "week_02" / "day_01.json").read_text(encoding="utf-8")
    )

    assert len(memory["lectures"]) == 2
    assert any(event["type"] == "homework" for event in memory["assessments"])
    assert "prior lecture memory" in week_two["transcript"]
    assert "Recent labs or assessments have checked the basics" in week_two["transcript"]
