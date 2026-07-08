"""Text extraction and chunking for inventoried source material."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.ingest import SUPPORTED_EXTENSIONS, InventoryResult
from aiu.models import ExtractionStatus, SourceManifestIndex
from aiu.state import complete_stage

TEXT_SOURCE_TYPES = {"text", "markdown", "json", "yaml", "csv", "code"}
MAX_CHUNK_CHARS = 1200


@dataclass
class ChunkRecord:
    """One extracted source chunk."""

    chunk_id: str
    source_id: str
    source_ref: str
    sequence: int
    text_ref: str
    char_start: int
    char_end: int
    checksum: str

    def to_json(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "checksum": self.checksum,
            "chunk_id": self.chunk_id,
            "sequence": self.sequence,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "text_ref": self.text_ref,
        }


@dataclass
class ExtractionResult:
    """Summary of extraction and chunking."""

    chunks: list[ChunkRecord] = field(default_factory=list)
    extracted_count: int = 0
    skipped_count: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "chunk_count": len(self.chunks),
            "error_count": len(self.errors),
            "errors": self.errors,
            "extracted_count": self.extracted_count,
            "skipped_count": self.skipped_count,
        }


def extract_and_chunk_sources(
    course_root: str | Path, inventory: InventoryResult
) -> ExtractionResult:
    """Extract readable sources, write text artifacts, and build a local chunk index."""

    store = ArtifactStore(course_root)
    extraction = ExtractionResult()

    for source in inventory.sources:
        source_path = inventory.source_paths.get(source.source_id)
        if source_path is None:
            source.extraction_status = ExtractionStatus.FAILED
            source.errors.append("source path unavailable for extraction")
            extraction.errors.append(
                {"source_id": source.source_id, "error": "source path unavailable for extraction"}
            )
            continue

        if source.type in TEXT_SOURCE_TYPES:
            extracted = _extract_text_file(store, source.source_id, source.path_or_url, source_path)
            if extracted is None:
                source.extraction_status = ExtractionStatus.FAILED
                source.errors.append("unable to read source as UTF-8 text")
                extraction.errors.append(
                    {"source_id": source.source_id, "error": "unable to read source as UTF-8 text"}
                )
                continue
            source_chunks = _chunks_for_text(
                source_id=source.source_id,
                source_ref=source.path_or_url,
                text_ref=extracted["text_ref"],
                text=extracted["text"],
            )
            source.chunks = [chunk.chunk_id for chunk in source_chunks]
            source.extraction_status = ExtractionStatus.EXTRACTED
            extraction.chunks.extend(source_chunks)
            extraction.extracted_count += 1
        elif source.type == "archive":
            archive_chunks = _extract_zip_archive(
                store, source.source_id, source.path_or_url, source_path
            )
            if archive_chunks is None:
                source.extraction_status = ExtractionStatus.FAILED
                source.errors.append("unable to read zip archive")
                extraction.errors.append(
                    {"source_id": source.source_id, "error": "unable to read zip archive"}
                )
                continue
            source.chunks = [chunk.chunk_id for chunk in archive_chunks]
            source.extraction_status = (
                ExtractionStatus.EXTRACTED if archive_chunks else ExtractionStatus.SKIPPED
            )
            if archive_chunks:
                extraction.extracted_count += 1
                extraction.chunks.extend(archive_chunks)
            else:
                source.errors.append("zip archive contained no supported text files")
                extraction.skipped_count += 1
        else:
            source.extraction_status = ExtractionStatus.SKIPPED
            reason = f"{source.type} extraction is not implemented yet"
            source.errors.append(reason)
            extraction.skipped_count += 1

    extraction.chunks.sort(key=lambda chunk: (chunk.source_ref, chunk.sequence, chunk.chunk_id))
    _write_extraction_artifacts(store, inventory, extraction)
    return extraction


def _extract_text_file(
    store: ArtifactStore,
    source_id: str,
    source_ref: str,
    source_path: Path,
) -> dict[str, str] | None:
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text_ref = f"extracted_sources/{source_id}.txt"
    store.write_markdown(text_ref, text)
    return {"text": text, "text_ref": text_ref, "source_ref": source_ref}


def _extract_zip_archive(
    store: ArtifactStore,
    source_id: str,
    source_ref: str,
    source_path: Path,
) -> list[ChunkRecord] | None:
    archive_chunks: list[ChunkRecord] = []
    try:
        with zipfile.ZipFile(source_path) as archive:
            for member in sorted(archive.infolist(), key=lambda item: item.filename):
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                if SUPPORTED_EXTENSIONS.get(member_path.suffix.lower()) not in TEXT_SOURCE_TYPES:
                    continue
                try:
                    raw = archive.read(member)
                except (OSError, zipfile.BadZipFile):
                    continue
                text = raw.decode("utf-8", errors="replace")
                safe_member_ref = _safe_member_ref(member.filename)
                text_ref = f"extracted_sources/{source_id}/{safe_member_ref}.txt"
                full_source_ref = f"{source_ref}!{member.filename}"
                store.write_markdown(text_ref, text)
                archive_chunks.extend(
                    _chunks_for_text(
                        source_id=source_id,
                        source_ref=full_source_ref,
                        text_ref=text_ref,
                        text=text,
                    )
                )
    except (OSError, zipfile.BadZipFile):
        return None
    return archive_chunks


def _chunks_for_text(
    *,
    source_id: str,
    source_ref: str,
    text_ref: str,
    text: str,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    if not text:
        return chunks

    start = 0
    sequence = 1
    while start < len(text):
        end = min(len(text), start + MAX_CHUNK_CHARS)
        chunk_text = text[start:end]
        chunk_id = stable_chunk_id(source_ref=source_ref, sequence=sequence, text=chunk_text)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                source_id=source_id,
                source_ref=source_ref,
                sequence=sequence,
                text_ref=text_ref,
                char_start=start,
                char_end=end,
                checksum=_sha256_text(chunk_text),
            )
        )
        start = end
        sequence += 1
    return chunks


def stable_chunk_id(*, source_ref: str, sequence: int, text: str) -> str:
    digest = hashlib.sha256(f"{source_ref}:{sequence}:{text}".encode()).hexdigest()[:16]
    return f"chunk_{digest}"


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _safe_member_ref(member_name: str) -> str:
    normalized = member_name.replace("\\", "/").strip("/")
    return re.sub(r"[^A-Za-z0-9._/-]+", "_", normalized).replace("/", "__")


def _write_extraction_artifacts(
    store: ArtifactStore,
    inventory: InventoryResult,
    extraction: ExtractionResult,
) -> None:
    chunks = [chunk.to_json() for chunk in extraction.chunks]
    store.write_json(
        "source_index/chunk_manifest.json",
        {"chunk_count": len(chunks), "chunks": chunks},
    )
    store.write_json(
        "source_index/search_index.json",
        {"entries": [_search_entry(store, chunk) for chunk in extraction.chunks]},
    )
    store.write_json("source_manifest.json", SourceManifestIndex(sources=inventory.sources))

    try:
        ingest_report = store.read_json("ingest_report.json")
    except FileNotFoundError:
        ingest_report = inventory.report()
    ingest_report["extraction"] = extraction.report()
    store.write_json("ingest_report.json", ingest_report)
    complete_stage(
        store.root,
        "context",
        [
            "source_manifest.json",
            "ingest_report.json",
            "source_index/chunk_manifest.json",
            "source_index/search_index.json",
        ],
    )


def _search_entry(store: ArtifactStore, chunk: ChunkRecord) -> dict[str, Any]:
    text = store.course_path(chunk.text_ref).read_text(encoding="utf-8")
    chunk_text = text[chunk.char_start : chunk.char_end]
    terms = sorted(set(re.findall(r"[a-z0-9]+", chunk_text.lower())))
    return {
        "chunk_id": chunk.chunk_id,
        "source_ref": chunk.source_ref,
        "terms": terms,
        "text_ref": chunk.text_ref,
    }
