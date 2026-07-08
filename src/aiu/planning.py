"""Deterministic course intent and blueprint generation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.auth import AuthStore
from aiu.config import CourseSettings, LabPolicy, ProviderName
from aiu.logging import ProgressCallback, content_snippet, emit_progress
from aiu.models import (
    AssessmentPlanEntry,
    AssessmentType,
    CourseBlueprint,
    CourseManifest,
    CourseModule,
    WeekPlan,
)
from aiu.project import update_manifest_artifacts
from aiu.providers import GenerationRequest, ProviderError, provider_for_name
from aiu.state import complete_stage, fail_stage, stage_is_complete, start_stage


class PlanningError(ValueError):
    """Raised when a course plan cannot be generated."""


def plan_course(
    course_root: str | Path, *, progress: ProgressCallback | None = None
) -> CourseBlueprint:
    """Generate deterministic intent analysis, blueprint, and schedule artifacts."""

    store = ArtifactStore(course_root)
    blueprint_artifacts = [
        "intent_analysis.json",
        "course_blueprint.json",
        "course_blueprint.md",
        "schedule.json",
    ]
    if stage_is_complete(course_root, "blueprint", blueprint_artifacts):
        emit_progress(
            progress,
            "blueprint",
            "Reusing completed course blueprint",
            artifact="course_blueprint.json",
            detail="Planning artifacts already exist and passed checkpoint validation.",
        )
        return CourseBlueprint.model_validate(store.read_json("course_blueprint.json"))

    manifest = CourseManifest.model_validate(store.read_json("manifest.json"))
    if manifest.prompt_ref is None:
        raise PlanningError("Cannot plan a course before prompt.md is stored.")

    start_stage(course_root, "blueprint")
    emit_progress(
        progress,
        "blueprint",
        "Analyzing learning goal and course settings",
        detail=(
            f"{manifest.settings.weeks} weeks, "
            f"{manifest.settings.lectures_per_week} lecture(s) per week, "
            f"{manifest.settings.lab_policy.value} lab policy"
        ),
    )
    if os.environ.get("AIU_FAIL_STAGE") == "blueprint":
        fail_stage(course_root, "blueprint", "simulated blueprint failure")
        raise PlanningError("Simulated blueprint failure requested by AIU_FAIL_STAGE.")

    prompt = store.course_path(manifest.prompt_ref).read_text(encoding="utf-8")
    settings = manifest.settings
    subject = _subject_from_prompt(prompt)
    emit_progress(
        progress,
        "blueprint",
        "Inferred course subject",
        detail=f"Subject: {content_snippet(subject, max_chars=120)}",
    )
    provider_plan_seed = _provider_plan_seed(prompt=prompt, settings=settings)
    if provider_plan_seed:
        emit_progress(
            progress,
            "blueprint",
            "Provider returned curriculum planning guidance",
            snippet=content_snippet(provider_plan_seed),
        )
    intent = _intent_analysis(
        subject=subject,
        prompt=prompt,
        settings=settings,
        provider_plan_seed=provider_plan_seed,
    )
    blueprint = _blueprint_from_intent(intent, settings)
    schedule = _schedule_from_blueprint(manifest.course_id, blueprint, settings)

    store.write_json("intent_analysis.json", intent)
    store.write_json("course_blueprint.json", blueprint)
    store.write_markdown("course_blueprint.md", _blueprint_markdown(blueprint))
    store.write_json("schedule.json", schedule)
    emit_progress(
        progress,
        "blueprint",
        "Created course blueprint",
        artifact="course_blueprint.md",
        detail=(
            f"{len(blueprint.week_plan)} weeks, {schedule['lecture_count']} lectures, "
            f"{len(blueprint.assessment_plan)} planned assessments"
        ),
        snippet=content_snippet(_blueprint_preview(blueprint)),
    )
    update_manifest_artifacts(
        course_root,
        [
            ("intent_analysis", "json", "intent_analysis.json"),
            ("course_blueprint_json", "json", "course_blueprint.json"),
            ("course_blueprint_markdown", "markdown", "course_blueprint.md"),
            ("schedule", "json", "schedule.json"),
        ],
    )
    complete_stage(course_root, "blueprint", blueprint_artifacts)
    return blueprint


def _blueprint_preview(blueprint: CourseBlueprint) -> str:
    first_week = blueprint.week_plan[0]
    first_outcome = blueprint.outcomes[0]
    return (
        f"{blueprint.course_title}. Week {first_week.week}: {first_week.title}. "
        f"First outcome: {first_outcome}"
    )


def _subject_from_prompt(prompt: str) -> str:
    text = " ".join(prompt.strip().split())
    text = re.sub(r"^(teach|help|show)\s+me\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(learn|understand)\s+", "", text, flags=re.IGNORECASE)
    text = text.strip(" .?!")
    return text or "the requested subject"


def _intent_analysis(
    *,
    subject: str,
    prompt: str,
    settings: CourseSettings,
    provider_plan_seed: str | None,
) -> dict[str, Any]:
    practical_balance = "applied" if settings.lab_policy != LabPolicy.NEVER else "conceptual"
    lab_usefulness = settings.lab_policy != LabPolicy.NEVER
    intent: dict[str, Any] = {
        "assumptions": [
            f"The learner wants a {settings.weeks}-week university-style course.",
            f"The configured level is {settings.level}.",
        ],
        "desired_depth": "semester",
        "lab_usefulness": lab_usefulness,
        "level": settings.level,
        "practical_vs_theoretical_balance": practical_balance,
        "prompt": prompt,
        "provider": settings.provider.value,
        "subject": subject,
        "topic_keywords": _keywords(subject),
    }
    if provider_plan_seed:
        intent["provider_plan_seed"] = provider_plan_seed
    return intent


def _blueprint_from_intent(intent: dict[str, Any], settings: CourseSettings) -> CourseBlueprint:
    subject = str(intent["subject"])
    title_subject = subject.title()
    outcomes = [
        f"Explain foundational concepts in {subject}.",
        f"Apply {subject} methods to realistic problems.",
        f"Evaluate tradeoffs, assumptions, and limitations in {subject}.",
        f"Communicate solutions using precise {subject} vocabulary.",
    ]
    weeks = list(range(1, settings.weeks + 1))
    modules = _modules(subject, weeks, outcomes)
    week_plan = [_week_plan(subject, week, settings) for week in weeks]
    assessment_plan = _assessment_plan(outcomes, settings)
    source_usage_plan = [
        "Use provided source chunks where available.",
        "Flag missing or unsupported source coverage before detailed generation.",
    ]
    if provider_plan_seed := intent.get("provider_plan_seed"):
        source_usage_plan.append(f"Provider planning guidance: {provider_plan_seed}")
    return CourseBlueprint(
        course_title=f"{title_subject}: AI University Course",
        description=(
            f"A structured {settings.weeks}-week course that builds from fundamentals "
            f"to applied work in {subject}."
        ),
        target_learner=settings.level,
        outcomes=outcomes,
        prerequisites=_prerequisites(settings.level),
        modules=modules,
        week_plan=week_plan,
        assessment_plan=assessment_plan,
        lab_policy=settings.lab_policy,
        lab_policy_rationale=_lab_policy_rationale(settings.lab_policy),
        source_usage_plan=source_usage_plan,
    )


def _modules(subject: str, weeks: list[int], outcomes: list[str]) -> list[CourseModule]:
    module_count = min(6, max(1, (len(weeks) + 3) // 4))
    modules: list[CourseModule] = []
    for index in range(module_count):
        start = index * len(weeks) // module_count
        end = (index + 1) * len(weeks) // module_count
        module_weeks = weeks[start:end]
        modules.append(
            CourseModule(
                module_id=f"module_{index + 1:02d}",
                title=f"{subject.title()} Module {index + 1}",
                weeks=module_weeks,
                objectives=[outcomes[index % len(outcomes)]],
                rationale="The module sequence introduces prerequisites before dependent topics.",
            )
        )
    return modules


def _week_plan(subject: str, week: int, settings: CourseSettings) -> WeekPlan:
    lecture_titles = [
        f"Week {week} Lecture {day}: {subject.title()} Topic {week}.{day}"
        for day in range(1, settings.lectures_per_week + 1)
    ]
    lab = None
    if settings.lab_policy == LabPolicy.ALWAYS:
        lab = f"Week {week} applied lab"
    elif settings.lab_policy == LabPolicy.AUTO:
        lab = f"Week {week} applied workshop"
    return WeekPlan(
        week=week,
        title=f"Week {week}: {subject.title()} Focus Area",
        topics=[f"{subject} concept {week}", f"{subject} practice {week}"],
        lecture_titles=lecture_titles,
        lab=lab,
        assessments=[f"homework_w{week:02d}", f"quiz_w{week:02d}" if week % 2 == 0 else ""],
    )


def _assessment_plan(outcomes: list[str], settings: CourseSettings) -> list[AssessmentPlanEntry]:
    plan: list[AssessmentPlanEntry] = []
    for week in range(1, settings.weeks + 1):
        plan.append(
            AssessmentPlanEntry(
                assessment_id=f"homework_w{week:02d}",
                type=AssessmentType.HOMEWORK,
                due_week=week,
                objectives=[outcomes[(week - 1) % len(outcomes)]],
                description=f"Weekly homework for week {week}.",
            )
        )
        if week % 2 == 0:
            plan.append(
                AssessmentPlanEntry(
                    assessment_id=f"quiz_w{week:02d}",
                    type=AssessmentType.QUIZ,
                    due_week=week,
                    objectives=[outcomes[(week - 1) % len(outcomes)]],
                    description=f"Short quiz for week {week}.",
                )
            )
    plan.append(
        AssessmentPlanEntry(
            assessment_id="midterm",
            type=AssessmentType.MIDTERM,
            due_week=max(1, settings.weeks // 2),
            objectives=outcomes[:2],
            description="Cumulative midterm assessment.",
        )
    )
    plan.append(
        AssessmentPlanEntry(
            assessment_id="final",
            type=AssessmentType.FINAL,
            due_week=settings.weeks,
            objectives=outcomes,
            description="Cumulative final assessment.",
        )
    )
    return plan


def _schedule_from_blueprint(
    course_id: str,
    blueprint: CourseBlueprint,
    settings: CourseSettings,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for week in blueprint.week_plan:
        for day, title in enumerate(week.lecture_titles, start=1):
            items.append(
                {
                    "day": day,
                    "duration_hours": settings.lecture_hours,
                    "id": f"lecture_w{week.week:02d}_d{day:02d}",
                    "title": title,
                    "type": "lecture",
                    "week": week.week,
                }
            )
        if week.lab is not None:
            items.append(
                {
                    "id": f"lab_w{week.week:02d}",
                    "title": week.lab,
                    "type": "lab" if settings.lab_policy == LabPolicy.ALWAYS else "activity",
                    "week": week.week,
                }
            )
    return {
        "course_id": course_id,
        "items": items,
        "lecture_count": settings.weeks * settings.lectures_per_week,
        "weeks": settings.weeks,
    }


def _blueprint_markdown(blueprint: CourseBlueprint) -> str:
    lines = [
        f"# {blueprint.course_title}",
        "",
        blueprint.description,
        "",
        "## Outcomes",
    ]
    lines.extend(f"- {outcome}" for outcome in blueprint.outcomes)
    lines.extend(["", "## Prerequisites"])
    lines.extend(f"- {item}" for item in (blueprint.prerequisites or ["None"]))
    lines.extend(["", "## Weekly Plan"])
    for week in blueprint.week_plan:
        lines.append(f"- Week {week.week}: {week.title}")
    lines.extend(["", "## Assessment Plan"])
    for assessment in blueprint.assessment_plan:
        lines.append(
            f"- {assessment.assessment_id} ({assessment.type.value}) due week {assessment.due_week}"
        )
    lines.extend(["", "## Lab Policy", f"{blueprint.lab_policy.value}"])
    return "\n".join(lines) + "\n"


def _prerequisites(level: str) -> list[str]:
    if level.lower() in {"advanced", "professional"}:
        return ["Prior intermediate coursework or equivalent experience."]
    if level.lower() == "intermediate":
        return ["Comfort with introductory terminology and basic study habits."]
    return ["No prior background required."]


def _keywords(subject: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[A-Za-z0-9]+", subject)][:8]


def _provider_plan_seed(*, prompt: str, settings: CourseSettings) -> str | None:
    if settings.provider == ProviderName.FAKE:
        return None

    auth_config = AuthStore().load().providers.get(settings.provider)
    if auth_config is None:
        raise PlanningError(
            f"Provider '{settings.provider.value}' is not configured. "
            f"Run `aiu auth login --provider {settings.provider.value}` first."
        )

    provider = provider_for_name(
        settings.provider,
        api_key_env=auth_config.api_key_env,
        codex_command=auth_config.codex_command,
    )
    try:
        result = provider.generate(
            GenerationRequest(
                prompt=(
                    "Create a concise planning note for a university-style course. "
                    "Return plain text only, no markdown headings.\n\n"
                    f"Learning prompt: {prompt}"
                ),
                purpose="course_plan_seed",
                system_prompt=(
                    "You are helping AI University turn a learning prompt into a "
                    "course plan. Be concise and curriculum-focused."
                ),
            )
        )
    except ProviderError as exc:
        raise PlanningError(str(exc)) from exc
    return result.text


def _lab_policy_rationale(lab_policy: LabPolicy) -> str:
    if lab_policy == LabPolicy.ALWAYS:
        return "Labs are required every week because the user selected the always policy."
    if lab_policy == LabPolicy.NEVER:
        return (
            "Labs are disabled; weekly seminar, case-study, or workshop alternatives "
            "will be generated."
        )
    return "Auto mode treats the subject as suitable for applied weekly practice by default."
