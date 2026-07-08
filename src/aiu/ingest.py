"""Local context inventory for course projects."""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.models import ExtractionStatus, SourceManifest, SourceManifestIndex
from aiu.state import complete_stage

CONTROL_FILES = {".aiuignore", ".gitignore"}
CONTROL_DIRS = {".git", ".aiu", "__pycache__"}
SUPPORTED_EXTENSIONS: dict[str, str] = {
    "": "text",
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".py": "code",
    ".js": "code",
    ".jsx": "code",
    ".ts": "code",
    ".tsx": "code",
    ".html": "code",
    ".css": "code",
    ".java": "code",
    ".c": "code",
    ".cc": "code",
    ".cpp": "code",
    ".h": "code",
    ".hpp": "code",
    ".rs": "code",
    ".go": "code",
    ".rb": "code",
    ".php": "code",
    ".sh": "code",
    ".sql": "code",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".zip": "archive",
}


@dataclass(frozen=True)
class InventoryRecord:
    """One inventory candidate and its context root."""

    path: Path
    context_root: Path

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(self.context_root).as_posix()
        except ValueError:
            return self.path.name


@dataclass
class InventoryResult:
    """Result of local context inventory."""

    sources: list[SourceManifest] = field(default_factory=list)
    source_paths: dict[str, Path] = field(default_factory=dict)
    ignored: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "accepted_count": len(self.sources),
            "error_count": len(self.errors),
            "ignored": self.ignored,
            "ignored_count": len(self.ignored),
            "skipped": self.skipped,
            "skipped_count": len(self.skipped),
            "source_count": len(self.sources),
        }


def inventory_context_paths(
    context_paths: tuple[str, ...] | list[str],
    *,
    excludes: tuple[str, ...] | list[str] = (),
) -> InventoryResult:
    """Inventory user-approved context files and directories."""

    result = InventoryResult()
    seen_source_ids: set[str] = set()

    for raw_context_path in context_paths:
        context_path = Path(raw_context_path).expanduser().resolve(strict=False)
        if not context_path.exists():
            result.errors.append({"path": raw_context_path, "error": "path does not exist"})
            continue

        records = _walk_context_path(context_path, excludes=tuple(excludes), result=result)
        for record in records:
            source = _source_from_record(record, result=result)
            if source is None:
                continue
            if source.source_id in seen_source_ids:
                continue
            seen_source_ids.add(source.source_id)
            result.sources.append(source)

    result.sources.sort(key=lambda source: source.path_or_url)
    return result


def write_inventory_artifacts(course_root: str | Path, result: InventoryResult) -> None:
    """Persist source manifest and ingest report."""

    store = ArtifactStore(course_root)
    store.write_json("source_manifest.json", SourceManifestIndex(sources=result.sources))
    store.write_json("ingest_report.json", result.report())
    complete_stage(course_root, "context", ["source_manifest.json", "ingest_report.json"])


def _walk_context_path(
    context_path: Path,
    *,
    excludes: tuple[str, ...],
    result: InventoryResult,
) -> list[InventoryRecord]:
    if context_path.is_file():
        return [InventoryRecord(path=context_path, context_root=context_path.parent)]

    if not context_path.is_dir():
        result.skipped.append({"path": context_path.as_posix(), "reason": "not a regular file"})
        return []

    ignore_patterns = _read_ignore_patterns(context_path) + list(excludes)
    records: list[InventoryRecord] = []
    for path in sorted(context_path.rglob("*")):
        relative_path = path.relative_to(context_path).as_posix()
        if any(part in CONTROL_DIRS for part in path.relative_to(context_path).parts):
            continue
        if path.name in CONTROL_FILES:
            continue
        if _matches_any_pattern(relative_path, path.name, ignore_patterns):
            result.ignored.append({"path": relative_path, "reason": "ignore pattern"})
            continue
        if path.is_dir():
            continue
        if path.is_file():
            records.append(InventoryRecord(path=path, context_root=context_path))
    return records


def _read_ignore_patterns(context_path: Path) -> list[str]:
    patterns: list[str] = []
    for ignore_file_name in (".gitignore", ".aiuignore"):
        ignore_file = context_path / ignore_file_name
        if not ignore_file.exists():
            continue
        try:
            raw_patterns = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for pattern in raw_patterns:
            stripped = pattern.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            patterns.append(stripped)
    return patterns


def _matches_any_pattern(
    relative_path: str, name: str, patterns: tuple[str, ...] | list[str]
) -> bool:
    return any(_matches_pattern(relative_path, name, pattern) for pattern in patterns)


def _matches_pattern(relative_path: str, name: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").strip()
    if not normalized:
        return False
    if normalized.endswith("/"):
        normalized = normalized.rstrip("/")
        return relative_path == normalized or relative_path.startswith(f"{normalized}/")
    if normalized.startswith("/"):
        return fnmatch.fnmatch(relative_path, normalized.lstrip("/"))
    if "/" in normalized:
        return fnmatch.fnmatch(relative_path, normalized)
    return fnmatch.fnmatch(name, normalized) or fnmatch.fnmatch(relative_path, normalized)


def _source_from_record(
    record: InventoryRecord,
    *,
    result: InventoryResult,
) -> SourceManifest | None:
    file_type = SUPPORTED_EXTENSIONS.get(record.path.suffix.lower())
    if file_type is None:
        result.skipped.append({"path": record.relative_path, "reason": "unsupported file type"})
        return None

    try:
        size = record.path.stat().st_size
        checksum = _sha256_file(record.path)
    except OSError as exc:
        result.skipped.append({"path": record.relative_path, "reason": str(exc)})
        return None

    source_id = stable_source_id(record.relative_path)
    source = SourceManifest(
        source_id=source_id,
        path_or_url=record.relative_path,
        type=file_type,
        checksum=checksum,
        extraction_status=ExtractionStatus.PENDING,
        chunks=[],
        citation_label=record.relative_path,
        size_bytes=size,
        errors=[],
    )
    result.source_paths[source_id] = record.path
    return source


def stable_source_id(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"source_{digest}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
