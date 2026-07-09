"""Durable source research notes for context-heavy course generation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.auth import AuthStore
from aiu.config import ProviderName
from aiu.logging import ProgressCallback, content_snippet, emit_progress
from aiu.models import CourseManifest
from aiu.project import update_manifest_artifacts
from aiu.providers import GenerationRequest, ProviderError, provider_for_name
from aiu.state import complete_stage, fail_stage, stage_is_complete, start_stage

CONTEXT_RESEARCH_JSON = "source_index/context_research.json"
CONTEXT_RESEARCH_MARKDOWN = "context_research.md"
CONTEXT_RESEARCH_ARTIFACTS = (CONTEXT_RESEARCH_JSON, CONTEXT_RESEARCH_MARKDOWN)

MAX_IDEA_CHUNKS = 32
MAX_KEY_SOURCES = 24
MAX_MODULES = 16
MAX_MODULE_SOURCES = 8
PROVIDER_MODULE_LIMIT = 8
PROVIDER_MODULE_CHUNKS = 6
PROVIDER_PACKET_CHARS = 9000
RESEARCH_PACKET_CHUNKS = 8
RESEARCH_PACKET_CHARS = 5600

RESEARCH_SYSTEM_PROMPT = (
    "You are AI University's context research lead. Study compact source packets before "
    "course planning. Your job is to identify the best modules, sources, citable chunks, "
    "course ideas, and coverage risks. Be concrete, cite source paths and chunk IDs, and "
    "write notes that a fresh agent can use without reading the whole repository."
)

STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "any",
    "are",
    "array",
    "because",
    "been",
    "before",
    "being",
    "bool",
    "can",
    "class",
    "const",
    "data",
    "def",
    "else",
    "false",
    "for",
    "from",
    "function",
    "get",
    "has",
    "have",
    "here",
    "his",
    "how",
    "include",
    "int",
    "into",
    "its",
    "let",
    "list",
    "long",
    "make",
    "new",
    "not",
    "null",
    "object",
    "one",
    "only",
    "our",
    "out",
    "path",
    "public",
    "return",
    "set",
    "should",
    "static",
    "str",
    "string",
    "struct",
    "that",
    "the",
    "their",
    "then",
    "there",
    "this",
    "true",
    "type",
    "use",
    "used",
    "using",
    "var",
    "was",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "you",
}


class ContextResearchError(ValueError):
    """Raised when source research cannot be generated."""


@dataclass(frozen=True)
class StudiedChunk:
    """A compact chunk record used by the research stage."""

    chunk_id: str
    source_ref: str
    sequence: int
    text_ref: str
    excerpt: str
    terms: list[str]
    score: int

    def to_json(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "excerpt": self.excerpt,
            "score": self.score,
            "sequence": self.sequence,
            "source_ref": self.source_ref,
            "summary": _chunk_summary(self),
            "terms": self.terms[:12],
            "text_ref": self.text_ref,
        }


def research_context(
    course_root: str | Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Study extracted context chunks and write durable source research notes."""

    store = ArtifactStore(course_root)
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return {}
    if not force and stage_is_complete(course_root, "research", CONTEXT_RESEARCH_ARTIFACTS):
        emit_progress(
            progress,
            "research",
            "Reusing completed context research notes",
            artifact=CONTEXT_RESEARCH_MARKDOWN,
        )
        return load_context_research(store)

    start_stage(course_root, "research")
    try:
        manifest = CourseManifest.model_validate(store.read_json("manifest.json"))
        prompt = _read_prompt(store, manifest)
        emit_progress(
            progress,
            "research",
            "Studying extracted source context",
            artifact="source_index/chunk_manifest.json",
            detail="Scanning every readable chunk before planning.",
        )
        chunks = _load_studied_chunks(store, prompt)
        deterministic = _deterministic_research(prompt=prompt, chunks=chunks)
        ai_research = _ai_research_if_available(
            store=store,
            manifest=manifest,
            prompt=prompt,
            research=deterministic,
            progress=progress,
        )
        research = {
            **deterministic,
            "ai_research": ai_research,
            "requirements": [
                "Fresh agents should read context_research.md before planning or generation.",
                "Course plans should use the listed source modules as recurring examples.",
                "Lectures should cite listed source paths and chunk IDs whenever relevant.",
                "Provider prompts must use compact research packets instead of full raw sources.",
            ],
            "version": 1,
        }
        store.write_json(CONTEXT_RESEARCH_JSON, research)
        store.write_markdown(CONTEXT_RESEARCH_MARKDOWN, _research_markdown(research))
        update_manifest_artifacts(
            course_root,
            [
                ("context_research_json", "json", CONTEXT_RESEARCH_JSON),
                ("context_research_notes", "markdown", CONTEXT_RESEARCH_MARKDOWN),
            ],
        )
        complete_stage(course_root, "research", CONTEXT_RESEARCH_ARTIFACTS)
        emit_progress(
            progress,
            "research",
            "Completed source research notes",
            artifact=CONTEXT_RESEARCH_MARKDOWN,
            detail=(
                f"{len(chunks)} chunk(s), "
                f"{len(research.get('source_modules', []))} module(s), "
                f"{len(research.get('idea_chunks', []))} idea chunk(s)"
            ),
            snippet=content_snippet(research.get("summary", "")),
        )
        return research
    except ContextResearchError:
        raise
    except (OSError, ValueError) as exc:
        fail_stage(course_root, "research", str(exc))
        raise ContextResearchError(str(exc)) from exc


def load_context_research(course_root_or_store: str | Path | ArtifactStore) -> dict[str, Any]:
    """Load saved context research if it exists."""

    store = (
        course_root_or_store
        if isinstance(course_root_or_store, ArtifactStore)
        else ArtifactStore(course_root_or_store)
    )
    if not store.course_path(CONTEXT_RESEARCH_JSON).exists():
        return {}
    return store.read_json(CONTEXT_RESEARCH_JSON)


def source_refs_from_research(store: ArtifactStore) -> list[str]:
    """Return source references prioritized by the research notes."""

    research = load_context_research(store)
    refs = [
        str(source.get("source_ref", ""))
        for source in research.get("key_sources", [])
        if source.get("source_ref")
    ]
    if refs:
        return _unique(refs)
    return _source_refs_from_chunk_manifest(store)


def research_packet_for_query(
    store: ArtifactStore,
    query: str,
    *,
    max_chunks: int = RESEARCH_PACKET_CHUNKS,
    char_limit: int = RESEARCH_PACKET_CHARS,
) -> dict[str, Any]:
    """Build a compact research packet for one planner or lecture query."""

    research = load_context_research(store)
    if not research:
        return _fallback_packet_from_chunks(
            store,
            query,
            max_chunks=max_chunks,
            char_limit=char_limit,
        )

    query_terms = _terms(query)
    idea_chunks = [
        chunk for chunk in research.get("idea_chunks", []) if isinstance(chunk, dict)
    ]
    scored_ideas = sorted(
        (
            (
                -_score_terms(query_terms, chunk.get("terms", []), chunk.get("excerpt", "")),
                index,
                chunk,
            )
            for index, chunk in enumerate(idea_chunks)
        ),
        key=lambda item: (item[0], item[1]),
    )
    selected_ideas = [chunk for _score, _index, chunk in scored_ideas[:max_chunks]]
    if not selected_ideas:
        selected_ideas = idea_chunks[:max_chunks]

    modules = _relevant_modules(research, query_terms)[:4]
    sections = [
        "Context research packet:",
        f"Research notes: {CONTEXT_RESEARCH_MARKDOWN}",
        f"Summary: {research.get('summary', 'No source research summary was available.')}",
    ]
    synthesis = str(research.get("ai_research", {}).get("synthesis", "")).strip()
    if synthesis:
        sections.append(f"AI research synthesis: {content_snippet(synthesis, max_chars=900)}")
    if modules:
        sections.append("Relevant source modules:")
        for module in modules:
            sections.append(
                "- "
                f"{module.get('name', 'source module')}: "
                f"{content_snippet(module.get('notes', ''), max_chars=260)}"
            )
    sections.append("High-value source chunks to cite:")

    source_refs: list[str] = []
    chunk_ids: list[str] = []
    remaining_chars = char_limit
    for chunk in selected_ideas:
        source_ref = str(chunk.get("source_ref", "local source"))
        chunk_id = str(chunk.get("chunk_id", "chunk"))
        source_refs.append(source_ref)
        chunk_ids.append(chunk_id)
        excerpt = content_snippet(str(chunk.get("excerpt", "")), max_chars=700)
        summary = content_snippet(str(chunk.get("summary", "")), max_chars=280)
        rendered = (
            f"Source: {source_ref} (chunk {chunk_id})\n"
            f"Research note: {summary}\n"
            f"Excerpt: {excerpt}"
        )
        if remaining_chars <= 0:
            break
        rendered = rendered[:remaining_chars].strip()
        if rendered:
            sections.append(rendered)
            remaining_chars -= len(rendered)

    if not source_refs:
        return _fallback_packet_from_chunks(
            store,
            query,
            max_chunks=max_chunks,
            char_limit=char_limit,
        )

    sections.append(
        "Citation instruction: cite these source paths and chunk IDs directly when they "
        "support a lecture claim; do not invent source names."
    )
    return {
        "chunk_ids": _unique(chunk_ids),
        "source_refs": _unique(source_refs),
        "text": "\n\n".join(sections),
    }


def _read_prompt(store: ArtifactStore, manifest: CourseManifest) -> str:
    if manifest.prompt_ref is None:
        return ""
    return store.course_path(manifest.prompt_ref).read_text(encoding="utf-8")


def _load_studied_chunks(store: ArtifactStore, prompt: str) -> list[StudiedChunk]:
    manifest = store.read_json("source_index/chunk_manifest.json")
    prompt_terms = _terms(prompt)
    chunks: list[StudiedChunk] = []
    for raw_chunk in manifest.get("chunks", []):
        excerpt = _chunk_excerpt(store, raw_chunk)
        if not excerpt:
            continue
        source_ref = str(raw_chunk.get("source_ref", "local source"))
        terms = _top_terms(f"{source_ref} {excerpt}", limit=24)
        score = _chunk_score(
            source_ref=source_ref,
            excerpt=excerpt,
            terms=terms,
            prompt_terms=prompt_terms,
        )
        chunks.append(
            StudiedChunk(
                chunk_id=str(raw_chunk["chunk_id"]),
                excerpt=content_snippet(excerpt, max_chars=900),
                score=score,
                sequence=int(raw_chunk.get("sequence", 0)),
                source_ref=source_ref,
                terms=terms,
                text_ref=str(raw_chunk.get("text_ref", "")),
            )
        )
    return sorted(chunks, key=lambda chunk: (-chunk.score, chunk.source_ref, chunk.sequence))


def _deterministic_research(*, prompt: str, chunks: list[StudiedChunk]) -> dict[str, Any]:
    source_stats: dict[str, dict[str, Any]] = defaultdict(_stats)
    module_stats: dict[str, dict[str, Any]] = defaultdict(_stats)
    global_terms: Counter[str] = Counter()

    for chunk in chunks:
        source_ref = _source_base(chunk.source_ref)
        module_key = _module_key(chunk.source_ref)
        for stats in (source_stats[source_ref], module_stats[module_key]):
            stats["chunk_count"] += 1
            stats["score"] += chunk.score
            stats["chunks"].append(chunk)
            stats["source_refs"].add(source_ref)
            stats["terms"].update(chunk.terms)
        global_terms.update(chunk.terms)

    key_sources = [
        _source_entry(source_ref, stats)
        for source_ref, stats in sorted(
            source_stats.items(),
            key=lambda item: (-item[1]["score"], item[0]),
        )[:MAX_KEY_SOURCES]
    ]
    source_modules = [
        _module_entry(module_key, stats)
        for module_key, stats in sorted(
            module_stats.items(),
            key=lambda item: (-item[1]["score"], item[0]),
        )[:MAX_MODULES]
    ]
    idea_chunks = [chunk.to_json() for chunk in chunks[:MAX_IDEA_CHUNKS]]
    top_terms = [term for term, _count in global_terms.most_common(24)]
    summary = _research_summary(
        prompt=prompt,
        chunks=chunks,
        top_terms=top_terms,
        key_sources=key_sources,
        source_modules=source_modules,
    )
    return {
        "chunk_count": len(chunks),
        "idea_chunks": idea_chunks,
        "key_sources": key_sources,
        "source_count": len(source_stats),
        "source_modules": source_modules,
        "summary": summary,
        "top_terms": top_terms,
    }


def _ai_research_if_available(
    *,
    store: ArtifactStore,
    manifest: CourseManifest,
    prompt: str,
    research: dict[str, Any],
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    if manifest.settings.provider == ProviderName.FAKE:
        return {"reason": "fake provider uses deterministic research notes", "status": "not_run"}

    auth_config = AuthStore().load().providers.get(manifest.settings.provider)
    if auth_config is None:
        fail_stage(
            store.root,
            "research",
            f"Provider '{manifest.settings.provider.value}' is not configured.",
        )
        raise ContextResearchError(
            f"Provider '{manifest.settings.provider.value}' is not configured. "
            f"Run `aiu auth login --provider {manifest.settings.provider.value}` first."
        )
    provider = provider_for_name(
        manifest.settings.provider,
        api_key_env=auth_config.api_key_env,
        codex_command=auth_config.codex_command,
    )

    module_notes: list[dict[str, str]] = []
    modules = research.get("source_modules", [])[:PROVIDER_MODULE_LIMIT]
    for index, module in enumerate(modules, start=1):
        packet = _provider_module_packet(research, module)
        emit_progress(
            progress,
            "research",
            "Asking provider to study source module",
            current=index,
            total=len(modules),
            detail=str(module.get("name", "source module")),
        )
        try:
            result = provider.generate(
                GenerationRequest(
                    prompt=_module_research_prompt(
                        learning_prompt=prompt,
                        module=module,
                        packet=packet,
                    ),
                    purpose="context_research_module",
                    system_prompt=RESEARCH_SYSTEM_PROMPT,
                    metadata={"module": str(module.get("module_id", index))},
                    max_retries=2,
                )
            )
        except ProviderError as exc:
            fail_stage(store.root, "research", str(exc))
            raise ContextResearchError(str(exc)) from exc
        note = result.text.strip()
        module_notes.append(
            {
                "module_id": str(module.get("module_id", f"module_{index:02d}")),
                "name": str(module.get("name", "source module")),
                "note": note,
            }
        )

    synthesis_packet = _provider_synthesis_packet(research, module_notes)
    emit_progress(
        progress,
        "research",
        "Asking provider to synthesize course source research",
        detail="Checking modules, source chunks, citation use, and coverage risks.",
    )
    try:
        synthesis = provider.generate(
            GenerationRequest(
                prompt=_synthesis_prompt(learning_prompt=prompt, packet=synthesis_packet),
                purpose="context_research_synthesis",
                system_prompt=RESEARCH_SYSTEM_PROMPT,
                max_retries=2,
            )
        ).text.strip()
    except ProviderError as exc:
        fail_stage(store.root, "research", str(exc))
        raise ContextResearchError(str(exc)) from exc
    return {"module_notes": module_notes, "status": "complete", "synthesis": synthesis}


def _stats() -> dict[str, Any]:
    return {
        "chunk_count": 0,
        "chunks": [],
        "score": 0,
        "source_refs": set(),
        "terms": Counter(),
    }


def _source_entry(source_ref: str, stats: dict[str, Any]) -> dict[str, Any]:
    chunks = sorted(stats["chunks"], key=lambda chunk: (-chunk.score, chunk.sequence))
    terms = [term for term, _count in stats["terms"].most_common(10)]
    return {
        "chunk_count": int(stats["chunk_count"]),
        "representative_chunks": [_chunk_reference(chunk) for chunk in chunks[:3]],
        "score": int(stats["score"]),
        "source_ref": source_ref,
        "summary": _source_summary(source_ref, terms, chunks),
        "top_terms": terms,
    }


def _module_entry(module_key: str, stats: dict[str, Any]) -> dict[str, Any]:
    chunks = sorted(
        stats["chunks"],
        key=lambda chunk: (-chunk.score, chunk.source_ref, chunk.sequence),
    )
    terms = [term for term, _count in stats["terms"].most_common(12)]
    source_refs = sorted(stats["source_refs"])[:MAX_MODULE_SOURCES]
    return {
        "chunk_count": int(stats["chunk_count"]),
        "module_id": _module_id(module_key),
        "name": module_key,
        "notes": _module_notes(module_key, terms, source_refs),
        "representative_chunks": [_chunk_reference(chunk) for chunk in chunks[:4]],
        "score": int(stats["score"]),
        "source_refs": source_refs,
        "top_terms": terms,
    }


def _chunk_reference(chunk: StudiedChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "source_ref": chunk.source_ref,
        "summary": _chunk_summary(chunk),
        "terms": chunk.terms[:8],
    }


def _source_summary(source_ref: str, terms: list[str], chunks: list[StudiedChunk]) -> str:
    topic = ", ".join(terms[:5]) if terms else "local source details"
    example = content_snippet(chunks[0].excerpt, max_chars=180) if chunks else ""
    return f"{source_ref} is a high-signal source for {topic}. Representative evidence: {example}"


def _module_notes(module_key: str, terms: list[str], source_refs: list[str]) -> str:
    topic = ", ".join(terms[:6]) if terms else "the supplied course context"
    refs = ", ".join(source_refs[:3]) if source_refs else "local source chunks"
    return (
        f"Use {module_key} as a recurring course module around {topic}. "
        f"Anchor lectures in {refs} and cite exact chunk IDs when making source-backed claims."
    )


def _chunk_summary(chunk: StudiedChunk) -> str:
    topic = ", ".join(chunk.terms[:5]) if chunk.terms else "local context"
    return f"Chunk {chunk.chunk_id} from {chunk.source_ref} supports discussion of {topic}."


def _research_summary(
    *,
    prompt: str,
    chunks: list[StudiedChunk],
    top_terms: list[str],
    key_sources: list[dict[str, Any]],
    source_modules: list[dict[str, Any]],
) -> str:
    prompt_label = content_snippet(prompt, max_chars=140) or "the requested course"
    terms = ", ".join(top_terms[:8]) if top_terms else "source-grounded details"
    sources = ", ".join(source["source_ref"] for source in key_sources[:4]) or "local sources"
    modules = ", ".join(module["name"] for module in source_modules[:4]) or "source modules"
    return (
        f"Reviewed {len(chunks)} extracted context chunk(s) for '{prompt_label}'. "
        f"Strong recurring terms include {terms}. Prioritize modules {modules}. "
        f"Use high-signal sources such as {sources} throughout the syllabus, lectures, labs, "
        "and assessments, citing source paths and chunk IDs from the research packet."
    )


def _provider_module_packet(research: dict[str, Any], module: dict[str, Any]) -> str:
    module_sources = set(module.get("source_refs", []))
    chunks = [
        chunk
        for chunk in research.get("idea_chunks", [])
        if chunk.get("source_ref", "").split("!", maxsplit=1)[0] in module_sources
        or chunk.get("source_ref", "") in module_sources
    ][:PROVIDER_MODULE_CHUNKS]
    lines = [
        f"Module: {module.get('name', 'source module')}",
        f"Deterministic module notes: {module.get('notes', '')}",
        f"Top terms: {', '.join(module.get('top_terms', []))}",
        "Representative chunks:",
    ]
    for chunk in chunks:
        lines.extend(
            [
                f"- Source: {chunk.get('source_ref')} (chunk {chunk.get('chunk_id')})",
                f"  Summary: {chunk.get('summary')}",
                f"  Excerpt: {content_snippet(chunk.get('excerpt', ''), max_chars=650)}",
            ]
        )
    return content_snippet("\n".join(lines), max_chars=PROVIDER_PACKET_CHARS)


def _module_research_prompt(*, learning_prompt: str, module: dict[str, Any], packet: str) -> str:
    return (
        "Study this compact source module packet for an AI University course.\n\n"
        f"Learning prompt:\n{learning_prompt}\n\n"
        f"Module under review: {module.get('name', 'source module')}\n\n"
        f"Source packet:\n{packet}\n\n"
        "Return concise markdown notes with these exact sections:\n"
        "1. What this module teaches well\n"
        "2. Best citable source paths and chunk IDs\n"
        "3. Lecture and lab ideas grounded in the sources\n"
        "4. Coverage risks or missing context\n"
        "Use source paths and chunk IDs from the packet."
    )


def _provider_synthesis_packet(
    research: dict[str, Any],
    module_notes: list[dict[str, str]],
) -> str:
    lines = [
        f"Deterministic summary: {research.get('summary', '')}",
        f"Top terms: {', '.join(research.get('top_terms', [])[:16])}",
        "Key sources:",
    ]
    for source in research.get("key_sources", [])[:10]:
        lines.append(f"- {source.get('source_ref')}: {source.get('summary')}")
    lines.append("Module notes:")
    for note in module_notes:
        lines.append(f"- {note['name']}: {content_snippet(note['note'], max_chars=900)}")
    return content_snippet("\n".join(lines), max_chars=PROVIDER_PACKET_CHARS)


def _synthesis_prompt(*, learning_prompt: str, packet: str) -> str:
    return (
        "Synthesize the source research for a course plan and future lecture generation.\n\n"
        f"Learning prompt:\n{learning_prompt}\n\n"
        f"Research packet:\n{packet}\n\n"
        "Return concise markdown with these exact sections:\n"
        "1. Source-grounded course thesis\n"
        "2. Modules and examples to reuse repeatedly\n"
        "3. Required citation behavior for lectures\n"
        "4. Fresh-agent reading notes\n"
        "5. Gaps to avoid overclaiming\n"
        "Be strict: the notes must force later agents to use the source paths and chunk IDs."
    )


def _research_markdown(research: dict[str, Any]) -> str:
    lines = [
        "# Context Research Notes",
        "",
        "These notes are the compact source-memory packet for this course. Fresh agents should "
        "read this file before planning, previewing, generating, or regenerating course work.",
        "",
        "## Research Scope",
        f"- Source count: {research.get('source_count', 0)}",
        f"- Chunk count: {research.get('chunk_count', 0)}",
        f"- Summary: {research.get('summary', '')}",
        "",
        "## Operating Requirements",
    ]
    lines.extend(f"- {item}" for item in research.get("requirements", []))
    ai_research = research.get("ai_research", {})
    if ai_research.get("status") == "complete":
        lines.extend(
            ["", "## AI Research Synthesis", "", str(ai_research.get("synthesis", ""))]
        )
        module_notes = ai_research.get("module_notes", [])
        if module_notes:
            lines.extend(["", "## AI Module Notes"])
            for note in module_notes:
                lines.extend(
                    ["", f"### {note.get('name', 'Source Module')}", "", note.get("note", "")]
                )
    else:
        lines.extend(
            [
                "",
                "## AI Research Synthesis",
                f"- Not run: {ai_research.get('reason', 'provider research was unavailable')}",
            ]
        )

    lines.extend(["", "## Source Modules"])
    for module in research.get("source_modules", []):
        lines.extend(
            [
                f"### {module.get('name', 'Source Module')}",
                f"- Chunk count: {module.get('chunk_count', 0)}",
                f"- Top terms: {', '.join(module.get('top_terms', []))}",
                f"- Notes: {module.get('notes', '')}",
                "- Representative chunks:",
            ]
        )
        for chunk in module.get("representative_chunks", []):
            lines.append(
                f"  - {chunk.get('source_ref')} "
                f"(chunk {chunk.get('chunk_id')}): {chunk.get('summary')}"
            )
        lines.append("")

    lines.extend(["", "## Key Sources"])
    for source in research.get("key_sources", []):
        lines.append(f"- {source.get('source_ref')}: {source.get('summary')}")

    lines.extend(["", "## Idea Chunks"])
    for chunk in research.get("idea_chunks", []):
        lines.extend(
            [
                f"### {chunk.get('source_ref')} (chunk {chunk.get('chunk_id')})",
                f"- Terms: {', '.join(chunk.get('terms', []))}",
                f"- Summary: {chunk.get('summary')}",
                f"- Excerpt: {chunk.get('excerpt')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


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


def _chunk_score(
    *,
    source_ref: str,
    excerpt: str,
    terms: list[str],
    prompt_terms: set[str],
) -> int:
    term_set = set(terms)
    score = len(term_set)
    score += 5 * len(term_set & prompt_terms)
    source_lower = source_ref.lower()
    if any(marker in source_lower for marker in ("readme", "docs/", "doc/", "overview")):
        score += 8
    if any(marker in source_lower for marker in ("src/", "source/", "server/", "client/", "data/")):
        score += 5
    if re.search(r"\b(class|def|function|struct|enum|interface|const)\b", excerpt):
        score += 4
    if re.search(r"^#{1,3}\s+", excerpt):
        score += 4
    return score


def _fallback_packet_from_chunks(
    store: ArtifactStore,
    query: str,
    *,
    max_chunks: int,
    char_limit: int,
) -> dict[str, Any]:
    chunk_manifest_path = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest_path.exists():
        return {
            "chunk_ids": [],
            "source_refs": [],
            "text": "No local source excerpts were available.",
        }
    query_terms = _terms(query)
    chunk_manifest = store.read_json("source_index/chunk_manifest.json")
    scored: list[tuple[int, int, str, str, str]] = []
    for index, chunk in enumerate(chunk_manifest.get("chunks", [])):
        excerpt = _chunk_excerpt(store, chunk)
        if not excerpt:
            continue
        source_ref = str(chunk.get("source_ref", "local source"))
        chunk_id = str(chunk.get("chunk_id", "chunk"))
        score = _score_terms(query_terms, _top_terms(f"{source_ref} {excerpt}"), excerpt)
        scored.append((-score, index, source_ref, chunk_id, excerpt))
    selected = sorted(scored)[:max_chunks]
    if not selected:
        return {
            "chunk_ids": [],
            "source_refs": [],
            "text": "No readable local source excerpts were available.",
        }
    sections = ["Available local source excerpts:"]
    refs: list[str] = []
    chunk_ids: list[str] = []
    remaining_chars = char_limit
    for _score, _index, source_ref, chunk_id, excerpt in selected:
        refs.append(source_ref)
        chunk_ids.append(chunk_id)
        rendered = (
            f"Source: {source_ref} (chunk {chunk_id})\n"
            f"{content_snippet(excerpt, max_chars=700)}"
        )
        rendered = rendered[:remaining_chars].strip()
        if not rendered:
            break
        sections.append(rendered)
        remaining_chars -= len(rendered)
    return {
        "chunk_ids": _unique(chunk_ids),
        "source_refs": _unique(refs),
        "text": "\n\n".join(sections),
    }


def _source_refs_from_chunk_manifest(store: ArtifactStore) -> list[str]:
    if not store.course_path("source_index/chunk_manifest.json").exists():
        return []
    chunk_manifest = store.read_json("source_index/chunk_manifest.json")
    return sorted(
        {
            str(chunk["source_ref"]).split("!", maxsplit=1)[0]
            for chunk in chunk_manifest.get("chunks", [])
            if chunk.get("source_ref")
        }
    )


def _relevant_modules(research: dict[str, Any], query_terms: set[str]) -> list[dict[str, Any]]:
    modules = [module for module in research.get("source_modules", []) if isinstance(module, dict)]
    return [
        module
        for _score, _index, module in sorted(
            (
                (
                    -_score_terms(
                        query_terms,
                        module.get("top_terms", []),
                        f"{module.get('name', '')} {module.get('notes', '')}",
                    ),
                    index,
                    module,
                )
                for index, module in enumerate(modules)
            ),
            key=lambda item: (item[0], item[1]),
        )
    ]


def _score_terms(query_terms: set[str], terms: Any, text: Any = "") -> int:
    candidate_terms = set(str(term).lower() for term in terms)
    candidate_terms |= _terms(str(text))
    return len(query_terms & candidate_terms) * 10 + min(len(candidate_terms), 30)


def _source_base(source_ref: str) -> str:
    return source_ref.split("!", maxsplit=1)[0]


def _module_key(source_ref: str) -> str:
    base = _source_base(source_ref).strip("/")
    parts = [part for part in base.split("/") if part]
    if not parts:
        return base or "local_sources"
    if len(parts) == 1:
        return parts[0]
    first = parts[0].lower()
    if first.endswith("-master") or first.endswith("-main"):
        return "/".join(parts[:2])
    if first in {"src", "source", "server", "client", "data", "docs", "test", "tests", "include"}:
        return "/".join(parts[:2])
    return "/".join(parts[:2])


def _module_id(module_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", module_key.lower()).strip("_")
    return f"module_{slug[:40] or 'local_sources'}"


def _terms(text: str) -> set[str]:
    return set(_top_terms(text, limit=200))


def _top_terms(text: str, *, limit: int = 16) -> list[str]:
    normalized = re.sub(r"[_/-]+", " ", text.lower())
    words = [
        word
        for word in re.findall(r"[a-z][a-z0-9]{2,}", normalized)
        if word not in STOPWORDS and not word.isdigit()
    ]
    counts = Counter(words)
    return [word for word, _count in counts.most_common(limit)]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
