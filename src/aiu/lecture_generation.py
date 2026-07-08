"""Lecture artifact and VR cue generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.auth import AuthStore
from aiu.config import ProviderName
from aiu.lecture_quality import minimum_transcript_words, transcript_word_count
from aiu.models import CourseBlueprint, CourseManifest, LectureSession, VRHandoffCue
from aiu.project import update_manifest_artifacts
from aiu.providers import GenerationRequest, ProviderAdapter, ProviderError, provider_for_name
from aiu.state import complete_stage, record_artifact_complete, stage_is_complete, start_stage

PROVIDER_CHUNK_WORD_TARGET = 1800
SOURCE_CONTEXT_CHAR_LIMIT = 4800
SOURCE_CONTEXT_CHUNK_LIMIT = 6
TRANSCRIPT_TAIL_WORDS = 140


LECTURE_SYSTEM_PROMPT = (
    "You are an AI University professor writing literal spoken lecture transcripts. "
    "Write natural professor speech with explanations, examples, transitions, checks for "
    "understanding, board-work cues, recap moments, and a closing synthesis. Return only "
    "transcript prose; do not return markdown headings, outlines, or metadata."
)


class LectureGenerationError(ValueError):
    """Raised when lecture artifacts cannot be generated."""


@dataclass(frozen=True)
class LectureGenerationContext:
    """Shared state for one lecture generation run."""

    store: ArtifactStore
    blueprint: CourseBlueprint
    manifest: CourseManifest
    source_refs: list[str]
    provider: ProviderAdapter | None


def generate_lecture_artifacts(course_root: str | Path, *, force: bool = False) -> list[str]:
    """Generate scheduled lecture Markdown, JSON, and VR cue artifacts."""

    store = ArtifactStore(course_root)
    schedule_path = store.course_path("schedule.json")
    approved_path = store.course_path("approved_course_blueprint.json")
    if not schedule_path.exists() or not approved_path.exists():
        raise LectureGenerationError("Cannot generate lectures before planning and approval.")

    schedule: dict[str, Any] = store.read_json("schedule.json")
    lecture_items = [item for item in schedule.get("items", []) if item.get("type") == "lecture"]
    artifacts = [artifact for item in lecture_items for artifact in _lecture_artifact_paths(item)]
    if not force and stage_is_complete(course_root, "lectures", artifacts):
        return artifacts

    start_stage(course_root, "lectures")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    source_refs = _source_refs(store)
    context = _lecture_generation_context(store, blueprint, source_refs)
    manifest_entries: list[tuple[str, str, str]] = []
    written_artifacts: list[str] = []

    for item in lecture_items:
        lecture = _lecture_session(item, context)
        markdown_path, json_path, cue_path = _lecture_artifact_paths(item)
        store.write_markdown(markdown_path, _lecture_markdown(lecture))
        store.write_json(json_path, lecture)
        store.write_json(cue_path, {"cues": lecture.vr_cues, "lecture_id": lecture.lecture_id})
        for path in (markdown_path, json_path, cue_path):
            record_artifact_complete(course_root, "lectures", path)
            written_artifacts.append(path)
        manifest_entries.extend(
            [
                (f"{lecture.lecture_id}_markdown", "markdown", markdown_path),
                (f"{lecture.lecture_id}_json", "json", json_path),
                (f"{lecture.lecture_id}_vr_cues", "json", cue_path),
            ]
        )

    update_manifest_artifacts(course_root, manifest_entries)
    complete_stage(course_root, "lectures", written_artifacts)
    return written_artifacts


def regenerate_lecture_artifact(course_root: str | Path, *, week: int, day: int) -> list[str]:
    """Regenerate one lecture and its VR cue."""

    store = ArtifactStore(course_root)
    item = _find_lecture_item(store, week=week, day=day)
    return _write_selected_lectures(course_root, [item], regenerated=True)


def generate_lecture_week_range(
    course_root: str | Path,
    *,
    start_week: int,
    end_week: int,
) -> list[str]:
    """Regenerate all lectures within an inclusive week range."""

    store = ArtifactStore(course_root)
    schedule: dict[str, Any] = store.read_json("schedule.json")
    items = [
        item
        for item in schedule.get("items", [])
        if item.get("type") == "lecture" and start_week <= int(item["week"]) <= end_week
    ]
    if not items:
        raise LectureGenerationError(f"No lectures found for week range {start_week}-{end_week}.")
    return _write_selected_lectures(course_root, items, regenerated=True)


def _write_selected_lectures(
    course_root: str | Path,
    items: list[dict[str, Any]],
    *,
    regenerated: bool,
) -> list[str]:
    store = ArtifactStore(course_root)
    if not store.course_path("approved_course_blueprint.json").exists():
        raise LectureGenerationError("Cannot generate lectures before planning and approval.")
    start_stage(course_root, "lectures")
    blueprint = CourseBlueprint.model_validate(store.read_json("approved_course_blueprint.json"))
    source_refs = _source_refs(store)
    context = _lecture_generation_context(store, blueprint, source_refs)
    written: list[str] = []
    manifest_entries: list[tuple[str, str, str] | tuple[str, str, str, dict[str, Any]]] = []
    metadata = {"regenerated": True} if regenerated else {}

    for item in items:
        lecture = _lecture_session(item, context)
        markdown_path, json_path, cue_path = _lecture_artifact_paths(item)
        store.write_markdown(markdown_path, _lecture_markdown(lecture))
        store.write_json(json_path, lecture)
        store.write_json(cue_path, {"cues": lecture.vr_cues, "lecture_id": lecture.lecture_id})
        for path in (markdown_path, json_path, cue_path):
            record_artifact_complete(course_root, "lectures", path)
            written.append(path)
        manifest_entries.extend(
            [
                (f"{lecture.lecture_id}_markdown", "markdown", markdown_path, metadata),
                (f"{lecture.lecture_id}_json", "json", json_path, metadata),
                (f"{lecture.lecture_id}_vr_cues", "json", cue_path, metadata),
            ]
        )
    update_manifest_artifacts(course_root, manifest_entries)
    complete_stage(course_root, "lectures", written)
    return written


def _find_lecture_item(store: ArtifactStore, *, week: int, day: int) -> dict[str, Any]:
    schedule: dict[str, Any] = store.read_json("schedule.json")
    for item in schedule.get("items", []):
        if item.get("type") == "lecture" and int(item["week"]) == week and int(item["day"]) == day:
            return item
    raise LectureGenerationError(f"No lecture found for week {week}, day {day}.")


def _lecture_session(
    item: dict[str, Any],
    context: LectureGenerationContext,
) -> LectureSession:
    lecture_id = str(item["id"])
    title = str(item["title"])
    week = int(item["week"])
    day = int(item["day"])
    duration_hours = float(item.get("duration_hours", context.manifest.settings.lecture_hours))
    objectives = [
        context.blueprint.outcomes[(week + day - 2) % len(context.blueprint.outcomes)],
        f"Connect week {week} material to the overall course plan.",
    ]
    minimum_words = minimum_transcript_words(duration_hours)
    transcript = _lecture_transcript(
        item=item,
        context=context,
        objectives=objectives,
        minimum_words=minimum_words,
        duration_hours=duration_hours,
    )
    return LectureSession(
        lecture_id=lecture_id,
        week=week,
        day=day,
        title=title,
        objectives=objectives,
        transcript=transcript,
        source_refs=context.source_refs,
        estimated_duration=duration_hours,
        vr_cues=_lecture_vr_cues(lecture_id, title),
    )


def _lecture_generation_context(
    store: ArtifactStore,
    blueprint: CourseBlueprint,
    source_refs: list[str],
) -> LectureGenerationContext:
    manifest = CourseManifest.model_validate(store.read_json("manifest.json"))
    provider = None
    if manifest.settings.provider != ProviderName.FAKE:
        auth_config = AuthStore().load().providers.get(manifest.settings.provider)
        if auth_config is None:
            raise LectureGenerationError(
                f"Provider '{manifest.settings.provider.value}' is not configured. "
                f"Run `aiu auth login --provider {manifest.settings.provider.value}` first."
            )
        provider = provider_for_name(
            manifest.settings.provider,
            api_key_env=auth_config.api_key_env,
            codex_command=auth_config.codex_command,
        )
    return LectureGenerationContext(
        store=store,
        blueprint=blueprint,
        manifest=manifest,
        source_refs=source_refs,
        provider=provider,
    )


def _lecture_transcript(
    *,
    item: dict[str, Any],
    context: LectureGenerationContext,
    objectives: list[str],
    minimum_words: int,
    duration_hours: float,
) -> str:
    if context.manifest.settings.provider == ProviderName.FAKE:
        return _fake_lecture_transcript(
            item=item,
            context=context,
            objectives=objectives,
            minimum_words=minimum_words,
            duration_hours=duration_hours,
        )
    return _provider_lecture_transcript(
        item=item,
        context=context,
        objectives=objectives,
        minimum_words=minimum_words,
        duration_hours=duration_hours,
    )


def _fake_lecture_transcript(
    *,
    item: dict[str, Any],
    context: LectureGenerationContext,
    objectives: list[str],
    minimum_words: int,
    duration_hours: float,
) -> str:
    title = str(item["title"])
    lecture_id = str(item["id"])
    week = int(item["week"])
    day = int(item["day"])
    week_plan = _week_plan_for(context.blueprint, week)
    topics = week_plan.topics if week_plan is not None else [title]
    source_note = (
        "We will connect this lecture to the local source references listed for the course."
        if context.source_refs
        else "No local source packet is attached, so we will work from the course blueprint."
    )
    paragraphs = [
        (
            f"Welcome to {title}. This is Week {week}, Day {day}, and the goal is to treat "
            f"the session like a real {duration_hours:g} hour university lecture rather than "
            "a summary. I will build the argument slowly, pause for checks, use examples, "
            "and keep connecting each idea back to the course outcomes. "
            f"{source_note} The lecture identifier for the generated course package is "
            f"{lecture_id}, but in the room we will simply treat this as today's class."
        )
    ]
    word_total = transcript_word_count(paragraphs[0])
    cycle = 1

    while word_total < minimum_words:
        topic = topics[(cycle - 1) % len(topics)]
        objective = objectives[(cycle - 1) % len(objectives)]
        lens = _fake_lens(cycle)
        activity = _fake_activity(cycle)
        paragraph = (
            f"Part {cycle}. Let us slow down and examine {topic} through {lens}. "
            f"The important objective is this: {objective} I would write that sentence on "
            "the board and ask everyone to copy it before we move on, because it gives us a "
            "stable reference point. The first idea is that technical architecture is not a "
            "pile of features; it is a set of choices about data, rules, constraints, and "
            "feedback. When those choices are explicit, a designer can test them, a developer "
            "can maintain them, and a learner can explain them without relying on vague "
            "intuition. For example, imagine a small change to a creature stat, an evolution "
            "rule, or a battle interaction. If that change is buried in scattered code, the "
            "team has to search, guess, and hope. If the change is represented as data with "
            "clear validation, the team can reason about it directly. Now pause and ask "
            f"yourself what evidence would prove that the design supports {topic}. "
            f"{activity} After that check, we return to the larger course question: how does "
            "this week's material help us build systems that are understandable, testable, "
            "and flexible enough for future lectures and assignments?"
        )
        paragraphs.append(paragraph)
        word_total += transcript_word_count(paragraph)
        cycle += 1

    paragraphs.append(
        "To close, notice how the details from today's lecture are not isolated facts. "
        "They are tools for thinking. A strong student should be able to restate the "
        "main concept, apply it to a new example, name the tradeoffs, and explain what "
        "would break if the assumptions changed. That is the standard we will carry "
        "into the next scheduled activity."
    )
    return "\n\n".join(paragraphs)


def _provider_lecture_transcript(
    *,
    item: dict[str, Any],
    context: LectureGenerationContext,
    objectives: list[str],
    minimum_words: int,
    duration_hours: float,
) -> str:
    if context.provider is None:
        raise LectureGenerationError(
            f"Provider '{context.manifest.settings.provider.value}' is unavailable."
        )

    lecture_id = str(item["id"])
    chunks: list[str] = []
    word_total = 0
    max_calls = max(1, (minimum_words + 999) // 1000 + 6)
    source_context = _source_context_for_prompt(context.store, item, context.blueprint, objectives)

    for call_number in range(1, max_calls + 1):
        remaining_words = minimum_words - word_total
        if remaining_words <= 0:
            break
        target_words = min(
            PROVIDER_CHUNK_WORD_TARGET,
            max(remaining_words + 150, 600),
        )
        request = GenerationRequest(
            prompt=_provider_lecture_prompt(
                item=item,
                context=context,
                objectives=objectives,
                source_context=source_context,
                target_words=target_words,
                written_words=word_total,
                transcript_tail=_transcript_tail(chunks),
                call_number=call_number,
                duration_hours=duration_hours,
                minimum_words=minimum_words,
            ),
            purpose="lecture_transcript",
            system_prompt=LECTURE_SYSTEM_PROMPT,
            metadata={"lecture_id": lecture_id, "chunk": str(call_number)},
            max_retries=2,
        )
        try:
            piece = context.provider.generate(request).text.strip()
        except ProviderError as exc:
            raise LectureGenerationError(
                f"Provider failed while generating lecture {lecture_id}: {exc}"
            ) from exc
        if not piece:
            raise LectureGenerationError(
                f"Provider returned an empty transcript chunk for lecture {lecture_id}."
            )
        chunks.append(piece)
        word_total += transcript_word_count(piece)

    transcript = "\n\n".join(chunks).strip()
    if transcript_word_count(transcript) < minimum_words:
        actual_words = transcript_word_count(transcript)
        raise LectureGenerationError(
            f"Generated transcript for {lecture_id} is too short: "
            f"{actual_words} words; required {minimum_words}."
        )
    return transcript


def _provider_lecture_prompt(
    *,
    item: dict[str, Any],
    context: LectureGenerationContext,
    objectives: list[str],
    source_context: str,
    target_words: int,
    written_words: int,
    transcript_tail: str,
    call_number: int,
    duration_hours: float,
    minimum_words: int,
) -> str:
    title = str(item["title"])
    week = int(item["week"])
    day = int(item["day"])
    objectives_text = "\n".join(f"- {objective}" for objective in objectives)
    continuation = (
        "This is the first portion of the transcript."
        if not transcript_tail
        else (
            "Continue naturally from this last passage, without repeating it:\n"
            f"{transcript_tail}"
        )
    )
    return (
        f"Write part {call_number} of one continuous lecture transcript.\n\n"
        f"Course: {context.blueprint.course_title}\n"
        f"Target learner: {context.blueprint.target_learner}\n"
        f"Lecture: {title}\n"
        f"Week: {week}\n"
        f"Day: {day}\n"
        f"Configured duration: {duration_hours:g} hours\n"
        f"Final transcript minimum: {minimum_words} words\n"
        f"Words already written: {written_words}\n"
        f"Write at least {target_words} new words in this response.\n\n"
        "Objectives:\n"
        f"{objectives_text}\n\n"
        "Week context:\n"
        f"{_week_context_for_prompt(context.blueprint, week)}\n\n"
        "Available local source excerpts:\n"
        f"{source_context}\n\n"
        "Requirements for this response:\n"
        "- Write professor speech only, as if delivered live in a lecture hall.\n"
        "- Include conceptual explanation, a concrete example, and a check for understanding.\n"
        "- Include natural transitions and occasional board-work or slide cues.\n"
        "- Do not include markdown headings, bullet lists, JSON, or metadata.\n"
        "- Do not end the entire lecture unless the final minimum has been reached.\n\n"
        f"{continuation}"
    )


def _source_context_for_prompt(
    store: ArtifactStore,
    item: dict[str, Any],
    blueprint: CourseBlueprint,
    objectives: list[str],
) -> str:
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return "No local source excerpts were available."

    chunk_manifest: dict[str, Any] = store.read_json("source_index/chunk_manifest.json")
    query_terms = _terms(
        " ".join(
            [
                str(item.get("title", "")),
                " ".join(objectives),
                _week_context_for_prompt(blueprint, int(item["week"])),
            ]
        )
    )
    scored_chunks: list[tuple[int, int, str, str]] = []
    for index, chunk in enumerate(chunk_manifest.get("chunks", [])):
        excerpt = _chunk_excerpt(store, chunk)
        if not excerpt:
            continue
        source_ref = str(chunk.get("source_ref", "local source"))
        score = len(query_terms & _terms(f"{source_ref} {excerpt}"))
        scored_chunks.append((-score, index, source_ref, excerpt))

    if not scored_chunks:
        return "No readable local source excerpts were available."

    selected: list[str] = []
    remaining_chars = SOURCE_CONTEXT_CHAR_LIMIT
    for _score, _index, source_ref, excerpt in sorted(scored_chunks)[:SOURCE_CONTEXT_CHUNK_LIMIT]:
        if remaining_chars <= 0:
            break
        clipped = excerpt[:remaining_chars].strip()
        if not clipped:
            continue
        selected.append(f"Source: {source_ref}\n{clipped}")
        remaining_chars -= len(clipped)
    if not selected:
        return "No readable local source excerpts were available."
    return "\n\n".join(selected)


def _chunk_excerpt(store: ArtifactStore, chunk: dict[str, Any]) -> str:
    text_ref = str(chunk.get("text_ref", ""))
    if not text_ref:
        return ""
    try:
        text = store.course_path(text_ref).read_text(encoding="utf-8")
    except OSError:
        return ""
    start = int(chunk.get("char_start", 0))
    end = int(chunk.get("char_end", len(text)))
    return " ".join(text[start:end].split())


def _terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9]+", text)}


def _transcript_tail(chunks: list[str]) -> str:
    if not chunks:
        return ""
    words = " ".join(chunks).split()
    return " ".join(words[-TRANSCRIPT_TAIL_WORDS:])


def _week_plan_for(blueprint: CourseBlueprint, week: int) -> Any | None:
    for week_plan in blueprint.week_plan:
        if week_plan.week == week:
            return week_plan
    return None


def _week_context_for_prompt(blueprint: CourseBlueprint, week: int) -> str:
    week_plan = _week_plan_for(blueprint, week)
    if week_plan is None:
        return f"Week {week} is part of {blueprint.course_title}."
    lecture_titles = "; ".join(week_plan.lecture_titles)
    topics = "; ".join(week_plan.topics)
    lab = f" Lab or workshop: {week_plan.lab}." if week_plan.lab else ""
    return f"{week_plan.title}. Topics: {topics}. Lectures this week: {lecture_titles}.{lab}"


def _fake_lens(cycle: int) -> str:
    lenses = [
        "the data model",
        "the player-facing rule",
        "the developer workflow",
        "the testing strategy",
        "the long-term maintenance question",
        "the balance between flexibility and clarity",
    ]
    return lenses[(cycle - 1) % len(lenses)]


def _fake_activity(cycle: int) -> str:
    activities = [
        "Turn to a neighbor and describe the smallest useful test you would write.",
        "Take thirty seconds to predict which assumption is most likely to fail.",
        "Sketch a tiny table with one row for data, one row for rules, and one row for feedback.",
        "Compare this example to a system you have used and identify one hidden dependency.",
        "Write down one question you would ask before implementing this in production.",
        "Pause here and separate what must be configurable from what should remain code.",
    ]
    return activities[(cycle - 1) % len(activities)]


def _lecture_vr_cues(lecture_id: str, title: str) -> list[VRHandoffCue]:
    cue_specs = [
        (
            "opening",
            "introduce objectives and write key terms on the board",
            f"{title} board outline",
        ),
        (
            "concepts",
            "explain the core architecture using a layered diagram",
            f"{title} concept diagram",
        ),
        (
            "example",
            "walk through a concrete example and annotate the tradeoffs",
            f"{title} worked example",
        ),
        (
            "check",
            "pause for a comprehension question and invite student responses",
            f"{title} check for understanding",
        ),
        (
            "closing",
            "summarize the lecture and preview the next activity",
            f"{title} closing recap",
        ),
    ]
    return [
        VRHandoffCue(
            cue_id=f"cue_{lecture_id}_{segment}",
            artifact_id=lecture_id,
            timestamp_or_segment=segment,
            scene_type="lecture_hall",
            professor_action=professor_action,
            visual_aid=visual_aid,
            interaction_anchor=f"{lecture_id}_{segment}_question",
        )
        for segment, professor_action, visual_aid in cue_specs
    ]


def _lecture_artifact_paths(item: dict[str, Any]) -> tuple[str, str, str]:
    week = int(item["week"])
    day = int(item["day"])
    lecture_id = str(item["id"])
    base = f"lectures/week_{week:02d}/day_{day:02d}"
    return (
        f"{base}.md",
        f"{base}.json",
        f"vr_handoff/lecture_scene_cues/{lecture_id}.json",
    )


def _lecture_markdown(lecture: LectureSession) -> str:
    lines = [
        f"# {lecture.title}",
        "",
        f"Lecture ID: {lecture.lecture_id}",
        f"Week {lecture.week}, Day {lecture.day}",
        "",
        "## Objectives",
        *[f"- {objective}" for objective in lecture.objectives],
        "",
        "## Transcript",
        lecture.transcript,
        "",
        "## Source References",
    ]
    if lecture.source_refs:
        lines.extend(f"- {source_ref}" for source_ref in lecture.source_refs)
    else:
        lines.append("- No local source references.")
    return "\n".join(lines) + "\n"


def _source_refs(store: ArtifactStore) -> list[str]:
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return []
    chunk_manifest: dict[str, Any] = store.read_json("source_index/chunk_manifest.json")
    return sorted(
        {
            str(chunk["source_ref"]).split("!", maxsplit=1)[0]
            for chunk in chunk_manifest.get("chunks", [])
            if chunk.get("source_ref")
        }
    )
