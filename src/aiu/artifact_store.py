"""Atomic artifact writing helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from aiu.models import portable_relative_path


class ArtifactWriteError(OSError):
    """Raised when an artifact cannot be written safely."""


class ArtifactStore:
    """Write JSON, YAML, and Markdown artifacts beneath one project root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def course_path(self, relative_path: str | Path) -> Path:
        """Resolve a safe course-relative path under the store root."""

        normalized = portable_relative_path(str(relative_path))
        return self.root / normalized

    def portable_path(self, path: str | Path) -> str:
        """Return a forward-slash relative path for manifest JSON."""

        candidate = Path(path)
        if candidate.is_absolute():
            candidate = candidate.resolve(strict=False).relative_to(self.root.resolve(strict=False))
        return portable_relative_path(candidate.as_posix())

    def write_json(self, relative_path: str | Path, payload: Any) -> Path:
        """Atomically write a stable, indented JSON artifact."""

        serializable = _to_jsonable(payload)
        text = json.dumps(serializable, indent=2, sort_keys=True) + "\n"
        path = self.course_path(relative_path)
        self._write_atomic(path, text)
        return path

    def write_yaml(self, relative_path: str | Path, payload: Any) -> Path:
        """Atomically write a YAML artifact."""

        serializable = _to_jsonable(payload)
        text = yaml.safe_dump(serializable, sort_keys=False)
        path = self.course_path(relative_path)
        self._write_atomic(path, text)
        return path

    def write_markdown(self, relative_path: str | Path, markdown: str) -> Path:
        """Atomically write Markdown text without altering user-provided content."""

        path = self.course_path(relative_path)
        self._write_atomic(path, markdown)
        return path

    def read_json(self, relative_path: str | Path) -> Any:
        """Read JSON from a course-relative artifact."""

        return json.loads(self.course_path(relative_path).read_text(encoding="utf-8"))

    def _write_atomic(self, target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(text)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            self._replace(temp_path, target)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ArtifactWriteError(f"Unable to write artifact: {target}") from exc

    def _replace(self, source: Path, target: Path) -> None:
        source.replace(target)


def _to_jsonable(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return {key: _to_jsonable(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_to_jsonable(value) for value in payload]
    if isinstance(payload, tuple):
        return [_to_jsonable(value) for value in payload]
    return payload
