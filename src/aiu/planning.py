"""Deterministic course intent and blueprint generation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.auth import AuthStore
from aiu.config import CourseSettings, LabPolicy, ProviderName
from aiu.context_research import ContextResearchError, research_context
from aiu.feedback import read_course_feedback
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


_FEEDBACK_STOPWORDS = {
    "about",
    "also",
    "and",
    "are",
    "cover",
    "covers",
    "for",
    "from",
    "include",
    "into",
    "looking",
    "make",
    "more",
    "please",
    "sure",
    "that",
    "the",
    "this",
    "topic",
    "topics",
    "want",
    "with",
}

_TYPO_REPLACEMENTS = {
    "soucce": "source",
    "tecnical": "technical",
    "technial": "technical",
    "undersand": "understand",
    "courese": "course",
    "prevview": "preview",
}

_NOISY_SOURCE_MARKERS = (
    "package-lock.json",
    "/translations/",
    "/node_modules/",
    "/vendor/",
    "help_system.c",
    "json.hpp",
)


def plan_course(
    course_root: str | Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> CourseBlueprint:
    """Generate deterministic intent analysis, blueprint, and schedule artifacts."""

    store = ArtifactStore(course_root)
    blueprint_artifacts = [
        "intent_analysis.json",
        "course_blueprint.json",
        "course_blueprint.md",
        "schedule.json",
    ]
    if not force and stage_is_complete(course_root, "blueprint", blueprint_artifacts):
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
    context_research: dict[str, Any] = {}
    if store.course_path("source_index/chunk_manifest.json").exists():
        try:
            context_research = research_context(course_root, progress=progress)
        except ContextResearchError as exc:
            raise PlanningError(str(exc)) from exc
        if context_research:
            emit_progress(
                progress,
                "blueprint",
                "Loaded context research notes for planning",
                artifact="context_research.md",
                detail=(
                    f"{context_research.get('chunk_count', 0)} chunk(s), "
                    f"{len(context_research.get('source_modules', []))} source module(s)"
                ),
                snippet=content_snippet(str(context_research.get("summary", ""))),
            )
    subject = _subject_from_prompt(prompt)
    emit_progress(
        progress,
        "blueprint",
        "Inferred course subject",
        detail=f"Subject: {content_snippet(subject, max_chars=120)}",
    )
    feedback = read_course_feedback(course_root)
    feedback_priorities = _feedback_priorities(feedback)
    if feedback_priorities:
        emit_progress(
            progress,
            "blueprint",
            "Loaded learner feedback for syllabus refinement",
            artifact="course_feedback.md",
            detail=f"{len(feedback_priorities)} requested coverage item(s)",
            snippet=content_snippet("; ".join(feedback_priorities)),
        )
    provider_plan_seed = None
    if not context_research:
        provider_plan_seed = _provider_plan_seed(
            prompt=prompt,
            settings=settings,
            feedback=feedback,
            context_research=context_research,
        )
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
        feedback=feedback,
        feedback_priorities=feedback_priorities,
        context_research=context_research,
        provider_plan_seed=provider_plan_seed,
    )
    if context_research:
        blueprint = _blueprint_from_context_research(
            prompt=prompt,
            subject=subject,
            settings=settings,
            feedback=feedback,
            feedback_priorities=feedback_priorities,
            context_research=context_research,
            progress=progress,
        )
        intent["curriculum_strategy"] = (
            "provider_research_blueprint"
            if settings.provider != ProviderName.FAKE
            else "deterministic_research_blueprint"
        )
    else:
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
    text = _copyedit_text(" ".join(prompt.strip().split()))
    text = re.split(r"\bIn the context\b|\bUsing the context\b", text, maxsplit=1)[0]
    text = re.split(r"[.?!]\s+", text, maxsplit=1)[0]
    text = re.sub(
        r"^(teach|help|show)\s+me\s+(to\s+)?(understand|learn)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(learn|understand)\s+", "", text, flags=re.IGNORECASE)
    text = text.strip(" .?!")
    text = re.sub(r"\barchitecture\s+architecture\b", "architecture", text, flags=re.IGNORECASE)
    if re.search(r"creature[- ]collector", text, flags=re.IGNORECASE):
        return "technical architecture of data-driven creature-collector RPGs"
    return content_snippet(text, max_chars=90) or "the requested subject"


def _copyedit_text(text: str) -> str:
    updated = str(text)
    for typo, replacement in _TYPO_REPLACEMENTS.items():
        updated = re.sub(rf"\b{re.escape(typo)}\b", replacement, updated, flags=re.IGNORECASE)
    return updated


def _intent_analysis(
    *,
    subject: str,
    prompt: str,
    settings: CourseSettings,
    feedback: str,
    feedback_priorities: list[str],
    context_research: dict[str, Any],
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
        "feedback": feedback,
        "feedback_priorities": feedback_priorities,
        "feedback_keywords": _feedback_keywords(feedback_priorities),
        "context_research": _research_intent_context(context_research),
        "research_priorities": _research_priorities(context_research),
        "topic_keywords": _keywords(subject),
    }
    if provider_plan_seed:
        intent["provider_plan_seed"] = provider_plan_seed
    return intent


def _blueprint_from_intent(intent: dict[str, Any], settings: CourseSettings) -> CourseBlueprint:
    subject = str(intent["subject"])
    title_subject = subject.title()
    feedback_priorities = [str(item) for item in intent.get("feedback_priorities", [])]
    research_priorities = [str(item) for item in intent.get("research_priorities", [])]
    research_context = intent.get("context_research", {})
    outcomes = [
        f"Explain foundational concepts in {subject}.",
        f"Apply {subject} methods to realistic problems.",
        f"Evaluate tradeoffs, assumptions, and limitations in {subject}.",
        f"Communicate solutions using precise {subject} vocabulary.",
    ]
    if feedback_priorities:
        outcomes.append(
            "Address learner-requested coverage including "
            f"{_summarize_priority_list(feedback_priorities, max_items=3)}."
        )
    if research_priorities:
        outcomes.append(
            "Use source-grounded examples from the supplied context including "
            f"{_summarize_priority_list(research_priorities, max_items=3)}."
        )
    weeks = list(range(1, settings.weeks + 1))
    modules = _modules(subject, weeks, outcomes)
    progression = _apply_feedback_to_progression(
        _curriculum_progression(subject, settings.weeks),
        feedback_priorities,
    )
    progression = _apply_research_to_progression(progression, research_priorities)
    week_plan = [
        _week_plan(subject, week, settings, focus=progression[week - 1])
        for week in weeks
    ]
    assessment_plan = _assessment_plan(outcomes, settings)
    source_usage_plan = [
        "Use provided source chunks where available.",
        "Read context_research.md before planning or generation and cite its source paths.",
        "Flag missing or unsupported source coverage before detailed generation.",
    ]
    if research_context:
        source_usage_plan.append(
            "Context research reviewed "
            f"{research_context.get('chunk_count', 0)} chunk(s) across "
            f"{research_context.get('source_count', 0)} source file(s)."
        )
        source_usage_plan.extend(
            f"Source-grounded module: {priority}"
            for priority in research_priorities[:6]
        )
    if feedback_priorities:
        source_usage_plan.extend(
            f"Learner feedback priority: {priority}" for priority in feedback_priorities
        )
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


def _blueprint_from_context_research(
    *,
    prompt: str,
    subject: str,
    settings: CourseSettings,
    feedback: str,
    feedback_priorities: list[str],
    context_research: dict[str, Any],
    progress: ProgressCallback | None,
) -> CourseBlueprint:
    if settings.provider != ProviderName.FAKE:
        blueprint = _provider_research_blueprint(
            prompt=prompt,
            subject=subject,
            settings=settings,
            feedback=feedback,
            feedback_priorities=feedback_priorities,
            context_research=context_research,
            progress=progress,
        )
    else:
        blueprint = _deterministic_research_blueprint(
            subject=subject,
            settings=settings,
            feedback_priorities=feedback_priorities,
            context_research=context_research,
        )
    return blueprint


def _deterministic_research_blueprint(
    *,
    subject: str,
    settings: CourseSettings,
    feedback_priorities: list[str],
    context_research: dict[str, Any],
) -> CourseBlueprint:
    modules = _curriculum_modules_from_research(context_research)
    if not modules:
        return _blueprint_from_intent(
            {
                "subject": subject,
                "feedback_priorities": feedback_priorities,
                "research_priorities": [],
                "context_research": _research_intent_context(context_research),
            },
            settings,
        )

    outcomes = _research_outcomes(subject, context_research, feedback_priorities)
    weeks: list[WeekPlan] = []
    for week in range(1, settings.weeks + 1):
        module = modules[(week - 1) % len(modules)]
        week_focus = _week_focus_from_module(module, week=week)
        lecture_titles = _lecture_titles_for_research_week(
            week_focus,
            lectures_per_week=settings.lectures_per_week,
        )
        lab = None
        if settings.lab_policy == LabPolicy.ALWAYS:
            lab = f"{week_focus['short']} source lab"
        elif settings.lab_policy == LabPolicy.AUTO:
            lab = f"{week_focus['short']} applied source workshop"
        weeks.append(
            WeekPlan(
                week=week,
                title=str(week_focus["title"]),
                topics=list(week_focus["topics"]),
                lecture_titles=lecture_titles,
                source_focus=list(week_focus["source_focus"]),
                lab=lab,
                assessments=[
                    f"homework_w{week:02d}",
                    f"quiz_w{week:02d}" if week % 2 == 0 else "",
                ],
            )
        )

    course_modules = _course_modules_from_research_modules(modules, settings.weeks, outcomes)
    return CourseBlueprint(
        course_title=f"{subject.title()}: AI University Course",
        description=_research_description(subject, context_research),
        target_learner=settings.level,
        outcomes=outcomes,
        prerequisites=_prerequisites(settings.level),
        modules=course_modules,
        week_plan=weeks,
        assessment_plan=_assessment_plan(outcomes, settings),
        lab_policy=settings.lab_policy,
        lab_policy_rationale=_lab_policy_rationale(settings.lab_policy),
        source_usage_plan=_source_usage_plan_from_research(
            context_research,
            feedback_priorities=feedback_priorities,
        ),
    )


def _provider_research_blueprint(
    *,
    prompt: str,
    subject: str,
    settings: CourseSettings,
    feedback: str,
    feedback_priorities: list[str],
    context_research: dict[str, Any],
    progress: ProgressCallback | None,
) -> CourseBlueprint:
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
    validation_errors: list[str] = []
    for attempt in range(1, 3):
        emit_progress(
            progress,
            "blueprint",
            "Requesting research-authored curriculum blueprint",
            current=attempt,
            total=2,
            detail=(
                "Provider must return validated JSON grounded in context_research.md."
            ),
        )
        try:
            result = provider.generate(
                GenerationRequest(
                    prompt=_provider_research_blueprint_prompt(
                        prompt=prompt,
                        subject=subject,
                        settings=settings,
                        feedback=feedback,
                        context_research=context_research,
                        validation_errors=validation_errors,
                    ),
                    purpose="context_research_blueprint",
                    system_prompt=(
                        "You are AI University's curriculum architect. Build the course "
                        "from source research, not from generic templates. Return JSON only."
                    ),
                    max_retries=2,
                )
            )
            payload = _json_object_from_provider_text(result.text)
            blueprint = _blueprint_from_provider_payload(
                payload,
                subject=subject,
                settings=settings,
                feedback_priorities=feedback_priorities,
                context_research=context_research,
                raw_prompt=prompt,
            )
        except (ProviderError, TypeError, ValueError) as exc:
            validation_errors = [str(exc)]
            continue
        emit_progress(
            progress,
            "blueprint",
            "Accepted research-authored curriculum blueprint",
            detail=blueprint.course_title,
        )
        return blueprint
    raise PlanningError(
        "Provider failed to return a valid research-authored curriculum blueprint: "
        + "; ".join(validation_errors)
    )


def _blueprint_from_provider_payload(
    payload: dict[str, Any],
    *,
    subject: str,
    settings: CourseSettings,
    feedback_priorities: list[str],
    context_research: dict[str, Any],
    raw_prompt: str,
) -> CourseBlueprint:
    course_title = _required_clean_string(payload, "course_title")
    description = _required_clean_string(payload, "description")
    outcomes = _required_string_list(payload, "outcomes", min_items=3)
    prerequisites = _optional_string_list(payload.get("prerequisites"))
    raw_weeks = payload.get("weeks", payload.get("week_plan"))
    if not isinstance(raw_weeks, list) or len(raw_weeks) != settings.weeks:
        raise ValueError(f"Expected exactly {settings.weeks} week plan item(s).")

    weeks: list[WeekPlan] = []
    for expected_week, raw_week in enumerate(raw_weeks, start=1):
        if not isinstance(raw_week, dict):
            raise ValueError(f"Week {expected_week} must be an object.")
        week_number = int(raw_week.get("week", expected_week))
        if week_number != expected_week:
            raise ValueError(f"Week plan must be sequential; expected week {expected_week}.")
        lecture_titles = _required_string_list(
            raw_week,
            "lecture_titles",
            min_items=settings.lectures_per_week,
        )
        if len(lecture_titles) != settings.lectures_per_week:
            raise ValueError(
                f"Week {expected_week} must include exactly "
                f"{settings.lectures_per_week} lecture title(s)."
            )
        source_focus = _required_string_list(raw_week, "source_focus", min_items=1)
        weeks.append(
            WeekPlan(
                week=expected_week,
                title=_required_clean_string(raw_week, "title"),
                topics=_required_string_list(raw_week, "topics", min_items=3)[:6],
                lecture_titles=lecture_titles,
                source_focus=source_focus[:8],
                lab=_optional_clean_string(raw_week.get("lab")),
                assessments=[
                    f"homework_w{expected_week:02d}",
                    f"quiz_w{expected_week:02d}" if expected_week % 2 == 0 else "",
                ],
            )
        )

    if _blueprint_contains_prompt_leak(
        course_title=course_title,
        description=description,
        outcomes=outcomes,
        weeks=weeks,
        raw_prompt=raw_prompt,
    ):
        raise ValueError("Provider curriculum copied raw prompt text or prompt typos.")

    modules = _provider_modules_or_default(payload, settings.weeks, outcomes, subject)
    return CourseBlueprint(
        course_title=course_title,
        description=description,
        target_learner=settings.level,
        outcomes=outcomes,
        prerequisites=prerequisites or _prerequisites(settings.level),
        modules=modules,
        week_plan=weeks,
        assessment_plan=_assessment_plan(outcomes, settings),
        lab_policy=settings.lab_policy,
        lab_policy_rationale=_lab_policy_rationale(settings.lab_policy),
        source_usage_plan=_source_usage_plan_from_research(
            context_research,
            feedback_priorities=feedback_priorities,
        ),
    )


def _modules(subject: str, weeks: list[int], outcomes: list[str]) -> list[CourseModule]:
    module_titles = [
        "Foundations and Scope",
        "Models, Data, and Architecture",
        "Interaction, Rules, and Feedback",
        "Quality, Operations, and Iteration",
        "Integration and Capstone",
        "Synthesis and Future Directions",
    ]
    module_count = min(6, max(1, (len(weeks) + 3) // 4))
    modules: list[CourseModule] = []
    for index in range(module_count):
        start = index * len(weeks) // module_count
        end = (index + 1) * len(weeks) // module_count
        module_weeks = weeks[start:end]
        modules.append(
            CourseModule(
                module_id=f"module_{index + 1:02d}",
                title=f"{module_titles[index]} in {subject.title()}",
                weeks=module_weeks,
                objectives=[outcomes[index % len(outcomes)]],
                rationale="The module sequence introduces prerequisites before dependent topics.",
            )
        )
    return modules


def _week_plan(
    subject: str,
    week: int,
    settings: CourseSettings,
    *,
    focus: dict[str, Any],
) -> WeekPlan:
    lecture_titles = [
        _lecture_title(subject, focus, day)
        for day in range(1, settings.lectures_per_week + 1)
    ]
    lab = None
    if settings.lab_policy == LabPolicy.ALWAYS:
        lab = f"{focus['short']} lab"
    elif settings.lab_policy == LabPolicy.AUTO:
        lab = f"{focus['short']} applied workshop"
    return WeekPlan(
        week=week,
        title=str(focus["title"]),
        topics=list(focus["topics"]),
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


def _feedback_priorities(feedback: str) -> list[str]:
    priorities: list[str] = []
    for raw_line in feedback.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line:
            priorities.append(content_snippet(line, max_chars=180))
    if not priorities and feedback.strip():
        priorities.append(content_snippet(feedback, max_chars=180))
    return priorities[:8]


def _feedback_keywords(priorities: list[str]) -> list[str]:
    keywords: list[str] = []
    for word in re.findall(r"[A-Za-z0-9]+", " ".join(priorities).lower()):
        if len(word) < 3 or word in _FEEDBACK_STOPWORDS or word in keywords:
            continue
        keywords.append(word)
        if len(keywords) == 12:
            break
    return keywords


def _summarize_priority_list(priorities: list[str], *, max_items: int) -> str:
    selected = [content_snippet(priority, max_chars=80) for priority in priorities[:max_items]]
    if len(priorities) > max_items:
        selected.append(f"{len(priorities) - max_items} more requested item(s)")
    return "; ".join(selected)


def _apply_feedback_to_progression(
    progression: list[dict[str, Any]],
    priorities: list[str],
) -> list[dict[str, Any]]:
    if not priorities or not progression:
        return progression

    updated = [
        {
            **focus,
            "topics": list(focus["topics"]),
            "lecture_angles": list(focus["lecture_angles"]),
        }
        for focus in progression
    ]
    for index, priority in enumerate(priorities):
        target_index = min(len(updated) - 1, index * len(updated) // max(1, len(priorities)))
        label = content_snippet(priority, max_chars=90)
        focus = updated[target_index]
        focus["topics"].append(f"learner-requested topic: {label}")
        focus["lecture_angles"].append(f"Requested coverage: {label}")
    return updated


def _apply_research_to_progression(
    progression: list[dict[str, Any]],
    priorities: list[str],
) -> list[dict[str, Any]]:
    if not priorities or not progression:
        return progression

    updated = [
        {
            **focus,
            "topics": list(focus["topics"]),
            "lecture_angles": list(focus["lecture_angles"]),
        }
        for focus in progression
    ]
    for index, priority in enumerate(priorities[: len(updated)]):
        target_index = min(len(updated) - 1, index * len(updated) // max(1, len(priorities)))
        label = content_snippet(priority, max_chars=90)
        focus = updated[target_index]
        focus["topics"].append(f"source-grounded case: {label}")
        focus["lecture_angles"].append(f"Source research case study: {label}")
    return updated


def _research_intent_context(context_research: dict[str, Any]) -> dict[str, Any]:
    if not context_research:
        return {}
    return {
        "ai_synthesis": content_snippet(
            str(context_research.get("ai_research", {}).get("synthesis", "")),
            max_chars=1000,
        ),
        "chunk_count": context_research.get("chunk_count", 0),
        "key_sources": [
            source.get("source_ref", "")
            for source in context_research.get("key_sources", [])[:10]
            if source.get("source_ref")
        ],
        "source_count": context_research.get("source_count", 0),
        "source_modules": [
            module.get("name", "")
            for module in context_research.get("source_modules", [])[:10]
            if module.get("name")
        ],
        "summary": context_research.get("summary", ""),
        "top_terms": context_research.get("top_terms", [])[:16],
    }


def _research_priorities(context_research: dict[str, Any]) -> list[str]:
    if not context_research:
        return []
    priorities: list[str] = []
    for module in context_research.get("source_modules", [])[:8]:
        name = str(module.get("name", "")).strip()
        terms = ", ".join(module.get("top_terms", [])[:5])
        if name:
            priorities.append(content_snippet(f"{name} ({terms})", max_chars=140))
    for chunk in context_research.get("idea_chunks", [])[:8]:
        source_ref = str(chunk.get("source_ref", "")).strip()
        chunk_id = str(chunk.get("chunk_id", "")).strip()
        terms = ", ".join(chunk.get("terms", [])[:4])
        if source_ref and chunk_id:
            priorities.append(
                content_snippet(f"{source_ref} chunk {chunk_id} ({terms})", max_chars=140)
            )
    return priorities[:12]


def _curriculum_modules_from_research(context_research: dict[str, Any]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for module in context_research.get("source_modules", []):
        if not isinstance(module, dict):
            continue
        name = str(module.get("name", "")).strip()
        if not name or _is_noisy_source_ref(name):
            continue
        modules.append(module)
    return modules[:12]


def _week_focus_from_module(module: dict[str, Any], *, week: int) -> dict[str, Any]:
    name = str(module.get("name", "source module"))
    terms = [str(term) for term in module.get("top_terms", []) if str(term).strip()]
    clean_terms = [term for term in terms if term not in {"master", "pokemon", "pokefirered"}]
    source_refs = [
        str(source_ref)
        for source_ref in module.get("source_refs", [])
        if str(source_ref).strip() and not _is_noisy_source_ref(str(source_ref))
    ][:4]
    topic_basis = clean_terms[:4] or terms[:4] or ["source architecture", "system behavior"]
    title = _title_from_source_module(name, topic_basis, week=week)
    return {
        "short": _short_source_label(name),
        "title": title,
        "topics": _topics_from_source_module(name, topic_basis),
        "source_focus": _source_focus_entries(name, source_refs, module),
    }


def _title_from_source_module(name: str, terms: list[str], *, week: int) -> str:
    if "pokemon-showdown-master/data" in name:
        return "Showdown Data Model, Dex Tables, and Versioned Battle Content"
    if "pokemon-showdown-master/sim" in name:
        return "Showdown Simulator Internals, Turn Flow, and Deterministic Battle State"
    if "pokemon-showdown-master/test" in name:
        return "Executable Battle Specifications Through Showdown Tests"
    if "pokemon-showdown-master/server" in name:
        return "Showdown Server Boundary Around the Battle Simulator"
    if "pokefirered-master/data" in name:
        return "FireRed Overworld Data: Maps, Layouts, Warps, and Progression Records"
    if "pokefirered-master/src" in name:
        return "FireRed Engine Source: Battle Entry, Party State, Saves, and Systems"
    if "pokefirered-master/include" in name:
        return "FireRed Engine Interfaces, Constants, and Cross-System Contracts"
    topic = ", ".join(terms[:3]) if terms else "source architecture"
    return f"Source Architecture Studio {week}: {name} ({topic})"


def _topics_from_source_module(name: str, terms: list[str]) -> list[str]:
    if "pokemon-showdown-master/data" in name:
        return [
            "Dex data tables for species, moves, abilities, items, formes, and learnsets",
            "Executable battle mechanics encoded as data records plus hook callbacks",
            "Generation-specific mods and legality data as versioned content architecture",
        ]
    if "pokemon-showdown-master/sim" in name:
        return [
            "Battle, Side, Pokemon, Dex, queue, and PRNG responsibilities in the simulator",
            "Turn resolution and battle protocol as deterministic state transitions",
            "How simulator internals consume data-layer records and hooks",
        ]
    if "pokemon-showdown-master/test" in name:
        return [
            "Battle tests as executable rules documentation",
            "Deterministic setup through createBattle, choices, assertions, and fixed state",
            "Using tests to learn engine contracts before extending mechanics",
        ]
    if "pokemon-showdown-master/server" in name:
        return [
            "Rooms, users, chat commands, plugins, and moderation around battle simulation",
            "Where multiplayer service responsibilities stop and simulator responsibilities begin",
            "Operational boundaries for a production battle server",
        ]
    if "pokefirered-master/data" in name:
        return [
            "Map layouts, warps, object events, coordinate triggers, and elevation records",
            "Overworld progression as data interpreted by engine systems",
            "How maps, encounters, trainer gates, and battle handoff fit together",
        ]
    if "pokefirered-master/src" in name:
        return [
            "C engine subsystems for battle setup, party state, summary screens, "
            "saves, and link play",
            "How decompiled source reveals full-game architecture beyond battle simulation",
            "Stateful RPG implementation tradeoffs under GBA-era constraints",
        ]
    if "pokefirered-master/include" in name:
        return [
            "Header contracts, constants, structs, and externs as architecture documentation",
            "Cross-system boundaries between battle, bag, field, party, and save systems",
            "Using declarations to map engine ownership before reading implementation files",
        ]
    return [
        f"Source-backed concept: {term}"
        for term in (terms[:4] or ["source architecture", "system responsibilities"])
    ]


def _source_focus_entries(
    name: str,
    source_refs: list[str],
    module: dict[str, Any],
) -> list[str]:
    entries = list(source_refs)
    for chunk in module.get("representative_chunks", []):
        if not isinstance(chunk, dict):
            continue
        source_ref = str(chunk.get("source_ref", "")).strip()
        chunk_id = str(chunk.get("chunk_id", "")).strip()
        if source_ref and chunk_id and not _is_noisy_source_ref(source_ref):
            entries.append(f"{source_ref} chunk {chunk_id}")
    if not entries:
        entries.append(f"{name}: source module research notes")
    return _unique_strings(entries)[:6]


def _lecture_titles_for_research_week(
    week_focus: dict[str, Any],
    *,
    lectures_per_week: int,
) -> list[str]:
    topics = list(week_focus["topics"])
    titles: list[str] = []
    for index in range(lectures_per_week):
        topic = topics[index % len(topics)]
        if index == 0:
            titles.append(f"{week_focus['short']}: {topic}")
        else:
            titles.append(f"{week_focus['short']} Source Workshop: {topic}")
    return titles


def _course_modules_from_research_modules(
    research_modules: list[dict[str, Any]],
    week_count: int,
    outcomes: list[str],
) -> list[CourseModule]:
    selected = research_modules[: min(6, max(1, len(research_modules)))]
    modules: list[CourseModule] = []
    for index, module in enumerate(selected):
        start = index * week_count // len(selected) + 1
        end = (index + 1) * week_count // len(selected)
        weeks = list(range(start, max(start, end) + 1))
        name = str(module.get("name", f"Source Module {index + 1}"))
        modules.append(
            CourseModule(
                module_id=f"module_{index + 1:02d}",
                title=f"Source Study: {name}",
                weeks=weeks,
                objectives=[outcomes[index % len(outcomes)]],
                rationale=(
                    "This module teaches directly from context_research.md source "
                    "findings rather than from a generic curriculum template."
                ),
            )
        )
    return modules


def _research_outcomes(
    subject: str,
    context_research: dict[str, Any],
    feedback_priorities: list[str],
) -> list[str]:
    modules = _curriculum_modules_from_research(context_research)
    module_names = [str(module.get("name", "")) for module in modules[:4]]
    source_phrase = (
        _summarize_priority_list(module_names, max_items=3)
        if module_names
        else "the supplied sources"
    )
    outcomes = [
        f"Explain {subject} using concrete evidence from {source_phrase}.",
        "Trace battle-system architecture from data tables through simulator behavior and tests.",
        "Trace full RPG architecture from overworld data through engine source, "
        "saves, and progression.",
        "Compare Pokemon Showdown's simulator architecture with pokefirered's "
        "decompiled full-game implementation.",
    ]
    if feedback_priorities:
        outcomes.append(
            "Address learner-requested coverage including "
            f"{_summarize_priority_list(feedback_priorities, max_items=3)}."
        )
    return outcomes


def _research_description(subject: str, context_research: dict[str, Any]) -> str:
    synthesis = str(context_research.get("ai_research", {}).get("synthesis", "")).strip()
    if synthesis:
        return (
            f"A source-grounded course in {subject}. It uses context_research.md to teach "
            "the concrete technical design of the supplied projects, including battle "
            "simulation, full-game implementation, overworld progression, and source-cited "
            "architecture tradeoffs."
        )
    return (
        f"A source-grounded course in {subject} that teaches directly from the supplied "
        "context research, source modules, and citable chunks."
    )


def _source_usage_plan_from_research(
    context_research: dict[str, Any],
    *,
    feedback_priorities: list[str],
) -> list[str]:
    plan = [
        "Use context_research.md as the compact source-memory packet for every stage.",
        "Teach concrete findings from the research notes; do not merely promise to "
        "inspect sources later.",
        "Cite source paths and chunk IDs from weekly source focus entries when making "
        "source-backed claims.",
    ]
    plan.append(
        "Context research reviewed "
        f"{context_research.get('chunk_count', 0)} chunk(s) across "
        f"{context_research.get('source_count', 0)} source file(s)."
    )
    for module in _curriculum_modules_from_research(context_research)[:8]:
        plan.append(f"Curriculum source module: {module.get('name')}")
    if feedback_priorities:
        plan.extend(f"Learner feedback priority: {priority}" for priority in feedback_priorities)
    return plan


def _provider_research_blueprint_prompt(
    *,
    prompt: str,
    subject: str,
    settings: CourseSettings,
    feedback: str,
    context_research: dict[str, Any],
    validation_errors: list[str],
) -> str:
    feedback_block = f"\nLearner feedback:\n{feedback.strip()}\n" if feedback.strip() else ""
    retry_block = ""
    if validation_errors:
        retry_block = (
            "\nYour previous response failed validation. Fix these issues:\n"
            + "\n".join(f"- {error}" for error in validation_errors)
            + "\n"
        )
    return (
        "Create the actual AI University course blueprint from the source research.\n"
        "The structure is deterministic, but the weekly content must be authored from "
        "context_research.md and the AI research synthesis.\n\n"
        f"Raw learning prompt, for intent only; do not copy wording or typos:\n{prompt}\n\n"
        f"Canonical subject: {subject}\n"
        f"Course length: {settings.weeks} weeks\n"
        f"Lectures per week: {settings.lectures_per_week}\n"
        f"Target learner: {settings.level}\n"
        f"Lab policy: {settings.lab_policy.value}\n"
        f"{feedback_block}"
        f"{_provider_research_block(context_research)}"
        f"{retry_block}\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "course_title": "concise corrected title",\n'
        '  "description": "source-grounded course description",\n'
        '  "outcomes": ["3-6 source-grounded learning outcomes"],\n'
        '  "prerequisites": ["..."],\n'
        '  "modules": [\n'
        '    {"title": "...", "weeks": [1, 2], "objectives": ["..."], '
        '"rationale": "..."}\n'
        "  ],\n"
        '  "weeks": [\n'
        '    {"week": 1, "title": "specific researched system", '
        '"topics": ["3-6 concrete concepts"], '
        '"lecture_titles": ["exactly the configured count"], '
        '"source_focus": ["source path and chunk ID or source path plus source-use note"], '
        '"lab": "optional concrete lab/workshop"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Do not include the raw prompt in any title, outcome, topic, or lecture title.\n"
        "- Correct obvious spelling mistakes from the prompt.\n"
        "- Do not use generic placeholder weeks like Foundations, Operations, or "
        "Capstone unless they name concrete researched systems.\n"
        "- Deliberately teach Pokemon Showdown battle architecture and pokefirered "
        "full-game/overworld architecture when those sources appear in research.\n"
        "- Every week must include source_focus entries from the research notes.\n"
    )


def _json_object_from_provider_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Provider did not return a JSON object.")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Provider returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Provider JSON root must be an object.")
    return payload


def _required_clean_string(payload: dict[str, Any], key: str) -> str:
    value = _optional_clean_string(payload.get(key))
    if not value:
        raise ValueError(f"Missing required string field: {key}.")
    return value


def _optional_clean_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _copyedit_text(" ".join(str(value).split())).strip()
    return cleaned or None


def _required_string_list(
    payload: dict[str, Any],
    key: str,
    *,
    min_items: int,
) -> list[str]:
    values = _optional_string_list(payload.get(key))
    if len(values) < min_items:
        raise ValueError(f"Field {key} must contain at least {min_items} item(s).")
    return values


def _optional_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings.")
    return [
        cleaned
        for item in value
        if (cleaned := _optional_clean_string(item))
    ]


def _provider_modules_or_default(
    payload: dict[str, Any],
    week_count: int,
    outcomes: list[str],
    subject: str,
) -> list[CourseModule]:
    raw_modules = payload.get("modules")
    modules: list[CourseModule] = []
    if isinstance(raw_modules, list):
        for index, raw_module in enumerate(raw_modules, start=1):
            if not isinstance(raw_module, dict):
                continue
            title = _optional_clean_string(raw_module.get("title"))
            raw_weeks = raw_module.get("weeks", [])
            weeks = [
                int(week)
                for week in raw_weeks
                if isinstance(week, int) and 1 <= int(week) <= week_count
            ]
            objectives = _optional_string_list(raw_module.get("objectives"))
            rationale = _optional_clean_string(raw_module.get("rationale"))
            if title and weeks and objectives and rationale:
                modules.append(
                    CourseModule(
                        module_id=f"module_{index:02d}",
                        title=title,
                        weeks=weeks,
                        objectives=objectives,
                        rationale=rationale,
                    )
                )
    if modules:
        return modules
    weeks = list(range(1, week_count + 1))
    return _modules(subject, weeks, outcomes)


def _blueprint_contains_prompt_leak(
    *,
    course_title: str,
    description: str,
    outcomes: list[str],
    weeks: list[WeekPlan],
    raw_prompt: str,
) -> bool:
    haystack = " ".join(
        [
            course_title,
            description,
            *outcomes,
            *[
                " ".join([week.title, *week.topics, *week.lecture_titles])
                for week in weeks
            ],
        ]
    ).lower()
    if any(typo in haystack for typo in _TYPO_REPLACEMENTS):
        return True
    prompt_words = [word.lower() for word in re.findall(r"[A-Za-z]{4,}", raw_prompt)]
    if len(prompt_words) < 12:
        return False
    phrase = " ".join(prompt_words[:12])
    return phrase in haystack


def _is_noisy_source_ref(source_ref: str) -> bool:
    normalized = source_ref.replace("\\", "/").lower()
    return any(marker in normalized for marker in _NOISY_SOURCE_MARKERS)


def _short_source_label(source_ref: str) -> str:
    normalized = source_ref.replace("\\", "/").strip("/")
    if "pokemon-showdown-master" in normalized:
        return normalized.replace("pokemon-showdown-master", "Pokemon Showdown")
    if "pokefirered-master" in normalized:
        return normalized.replace("pokefirered-master", "FireRed")
    return normalized or "Source Module"


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _curriculum_progression(subject: str, week_count: int) -> list[dict[str, Any]]:
    """Create a non-repetitive course arc from foundations to capstone."""

    arc = _curriculum_arc()
    if week_count <= len(arc):
        if week_count == 1:
            selected = [arc[0]]
        else:
            selected = [
                arc[round(index * (len(arc) - 1) / (week_count - 1))]
                for index in range(week_count)
            ]
    else:
        selected = list(arc)
        for week in range(len(arc) + 1, week_count + 1):
            selected.append(
                {
                    "short": f"Advanced studio {week - len(arc)}",
                    "title": f"Advanced Studio {week - len(arc)}: Specialized Problems",
                    "topics": [
                        f"specialized {subject} design problem {week - len(arc)}",
                        "research critique and implementation tradeoffs",
                        "portfolio-ready refinement",
                    ],
                    "lecture_angles": [
                        "Specialized problem framing",
                        "Advanced implementation critique",
                        "Research and extension workshop",
                    ],
                }
            )
    return [_focus_for_subject(subject, focus) for focus in selected]


def _curriculum_arc() -> list[dict[str, Any]]:
    return [
        {
            "short": "Course map and vocabulary",
            "title": "Course Map, Core Vocabulary, and Success Criteria",
            "topics": ["course scope", "core vocabulary", "success criteria"],
            "lecture_angles": ["Problem space and learning map", "Core vocabulary in practice"],
        },
        {
            "short": "Domain boundaries",
            "title": "Domain Boundaries, Requirements, and User Goals",
            "topics": ["domain boundaries", "requirements", "learner or user goals"],
            "lecture_angles": ["Requirements and constraints", "User goals and tradeoffs"],
        },
        {
            "short": "Core models",
            "title": "Core Models, Entities, and Relationships",
            "topics": ["entities", "relationships", "conceptual model"],
            "lecture_angles": ["Entity model design", "Relationship modeling workshop"],
        },
        {
            "short": "Data design",
            "title": "Data Schemas, Identifiers, and Change Management",
            "topics": ["schemas", "identifiers", "data evolution"],
            "lecture_angles": ["Schema design", "Versioning and migration choices"],
        },
        {
            "short": "Rules and validation",
            "title": "Rules, Constraints, and Validation",
            "topics": ["rule systems", "constraints", "validation strategy"],
            "lecture_angles": ["Rules as explicit systems", "Validation and edge cases"],
        },
        {
            "short": "Progression and feedback",
            "title": "Progression Systems and Feedback Loops",
            "topics": ["progression", "feedback loops", "motivation and pacing"],
            "lecture_angles": ["Progression model", "Feedback loop design"],
        },
        {
            "short": "Runtime architecture",
            "title": "Runtime Architecture and System Boundaries",
            "topics": ["architecture", "boundaries", "runtime responsibilities"],
            "lecture_angles": ["Architecture layers", "Boundary and dependency critique"],
        },
        {
            "short": "Authoring workflow",
            "title": "Authoring Tools, Content Workflow, and Collaboration",
            "topics": ["authoring tools", "content workflow", "collaboration"],
            "lecture_angles": ["Authoring workflow", "Tooling and review process"],
        },
        {
            "short": "State and persistence",
            "title": "State, Persistence, Saves, and Recovery",
            "topics": ["state", "persistence", "recovery"],
            "lecture_angles": ["State model", "Persistence and recovery cases"],
        },
        {
            "short": "Interaction systems",
            "title": "Interaction Systems and Moment-to-Moment Flow",
            "topics": ["interaction loops", "state transitions", "flow"],
            "lecture_angles": ["Interaction loop anatomy", "Flow and transition design"],
        },
        {
            "short": "Balance and tuning",
            "title": "Balancing, Tuning, and Evaluation Metrics",
            "topics": ["balancing", "tuning", "metrics"],
            "lecture_angles": ["Balancing strategy", "Metrics and iteration workshop"],
        },
        {
            "short": "Midcourse integration",
            "title": "Midcourse Integration and Architecture Review",
            "topics": ["integration", "architecture review", "risk assessment"],
            "lecture_angles": ["Integration review", "Risk and tradeoff critique"],
        },
        {
            "short": "Extensibility",
            "title": "Extensibility, Modularity, and Future Features",
            "topics": ["extensibility", "modularity", "future feature design"],
            "lecture_angles": ["Extension points", "Modularity tradeoffs"],
        },
        {
            "short": "Testing strategy",
            "title": "Testing Strategy and Quality Gates",
            "topics": ["testing", "quality gates", "regression prevention"],
            "lecture_angles": ["Test plan design", "Quality gates and failure modes"],
        },
        {
            "short": "Performance",
            "title": "Performance, Scale, and Reliability",
            "topics": ["performance", "scale", "reliability"],
            "lecture_angles": ["Performance model", "Reliability under load"],
        },
        {
            "short": "Experience design",
            "title": "Experience Design, Onboarding, and Accessibility",
            "topics": ["experience design", "onboarding", "accessibility"],
            "lecture_angles": ["Onboarding path", "Accessibility and usability critique"],
        },
        {
            "short": "Observability",
            "title": "Observability, Analytics, and Debugging",
            "topics": ["observability", "analytics", "debugging"],
            "lecture_angles": ["Instrumentation model", "Debugging and analytics review"],
        },
        {
            "short": "Security and safety",
            "title": "Security, Safety, Privacy, and Abuse Cases",
            "topics": ["security", "safety", "privacy"],
            "lecture_angles": ["Security boundaries", "Safety and abuse-case review"],
        },
        {
            "short": "Team workflow",
            "title": "Team Workflow, Versioning, and Release Discipline",
            "topics": ["team workflow", "versioning", "release discipline"],
            "lecture_angles": ["Team workflow", "Versioning and release practice"],
        },
        {
            "short": "Operations",
            "title": "Deployment, Operations, and Long-Term Maintenance",
            "topics": ["deployment", "operations", "maintenance"],
            "lecture_angles": ["Operational model", "Maintenance and ownership"],
        },
        {
            "short": "Capstone planning",
            "title": "Capstone Planning and Design Defense",
            "topics": ["capstone planning", "design defense", "scope control"],
            "lecture_angles": ["Capstone proposal", "Design defense workshop"],
        },
        {
            "short": "Capstone build",
            "title": "Capstone Implementation and Integration Studio",
            "topics": ["implementation", "integration", "iteration"],
            "lecture_angles": ["Implementation strategy", "Integration workshop"],
        },
        {
            "short": "Capstone critique",
            "title": "Capstone Critique, Polish, and Validation",
            "topics": ["critique", "polish", "validation"],
            "lecture_angles": ["Critique and polish", "Validation against outcomes"],
        },
        {
            "short": "Final synthesis",
            "title": "Final Synthesis and Future Learning Path",
            "topics": ["synthesis", "future learning", "transfer"],
            "lecture_angles": ["Course synthesis", "Future directions and transfer"],
        },
    ]


def _focus_for_subject(subject: str, focus: dict[str, Any]) -> dict[str, Any]:
    return {
        "short": str(focus["short"]),
        "title": str(focus["title"]),
        "topics": [f"{topic} for {subject}" for topic in focus["topics"]],
        "lecture_angles": list(focus["lecture_angles"]),
    }


def _lecture_title(subject: str, focus: dict[str, Any], day: int) -> str:
    angles = list(focus["lecture_angles"])
    if day <= len(angles):
        angle = angles[day - 1]
    else:
        angle = f"Applied studio {day - len(angles)}"
    return f"{angle}: {focus['short']} in {subject.title()}"


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
        lines.append(f"  - Topics: {', '.join(week.topics)}")
        if week.source_focus:
            lines.append(f"  - Source focus: {'; '.join(week.source_focus)}")
    lines.extend(["", "## Assessment Plan"])
    for assessment in blueprint.assessment_plan:
        lines.append(
            f"- {assessment.assessment_id} ({assessment.type.value}) due week {assessment.due_week}"
        )
    lines.extend(["", "## Lab Policy", f"{blueprint.lab_policy.value}"])
    if blueprint.source_usage_plan:
        lines.extend(["", "## Source and Feedback Usage"])
        lines.extend(f"- {item}" for item in blueprint.source_usage_plan)
    return "\n".join(lines) + "\n"


def _prerequisites(level: str) -> list[str]:
    if level.lower() in {"advanced", "professional"}:
        return ["Prior intermediate coursework or equivalent experience."]
    if level.lower() == "intermediate":
        return ["Comfort with introductory terminology and basic study habits."]
    return ["No prior background required."]


def _keywords(subject: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[A-Za-z0-9]+", subject)][:8]


def _provider_plan_seed(
    *,
    prompt: str,
    settings: CourseSettings,
    feedback: str,
    context_research: dict[str, Any],
) -> str | None:
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
    feedback_block = ""
    if feedback.strip():
        feedback_block = (
            "\n\nLearner feedback to incorporate into the course plan:\n"
            f"{feedback.strip()}"
        )
    research_block = _provider_research_block(context_research)
    try:
        result = provider.generate(
            GenerationRequest(
                prompt=(
                    "Create a concise planning note for a university-style course. "
                    "Use the context research notes heavily. Return plain text only, "
                    "no markdown headings.\n\n"
                    f"Learning prompt: {prompt}{feedback_block}{research_block}"
                ),
                purpose="course_plan_seed",
                system_prompt=(
                    "You are helping AI University turn a learning prompt into a "
                    "course plan. Be concise, curriculum-focused, and strict about "
                    "source-grounded coverage from context_research.md."
                ),
            )
        )
    except ProviderError as exc:
        raise PlanningError(str(exc)) from exc
    return result.text


def _provider_research_block(context_research: dict[str, Any]) -> str:
    if not context_research:
        return ""
    lines = [
        "",
        "",
        "Context research notes to enforce:",
        f"Summary: {context_research.get('summary', '')}",
        f"Top terms: {', '.join(context_research.get('top_terms', [])[:16])}",
        "Key source modules:",
    ]
    for module in context_research.get("source_modules", [])[:8]:
        lines.append(f"- {module.get('name')}: {module.get('notes')}")
    lines.append("Key citable sources:")
    for source in context_research.get("key_sources", [])[:8]:
        lines.append(f"- {source.get('source_ref')}: {source.get('summary')}")
    synthesis = str(context_research.get("ai_research", {}).get("synthesis", "")).strip()
    if synthesis:
        lines.extend(["AI research synthesis:", content_snippet(synthesis, max_chars=1200)])
    return "\n".join(lines)


def _lab_policy_rationale(lab_policy: LabPolicy) -> str:
    if lab_policy == LabPolicy.ALWAYS:
        return "Labs are required every week because the user selected the always policy."
    if lab_policy == LabPolicy.NEVER:
        return (
            "Labs are disabled; weekly seminar, case-study, or workshop alternatives "
            "will be generated."
        )
    return "Auto mode treats the subject as suitable for applied weekly practice by default."
