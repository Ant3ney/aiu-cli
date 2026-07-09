"""Deterministic course intent and blueprint generation."""

from __future__ import annotations

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
