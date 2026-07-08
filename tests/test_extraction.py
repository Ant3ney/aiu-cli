from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


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


def chunk_ids(course_root: Path) -> list[str]:
    manifest = json.loads(
        (course_root / "source_index" / "chunk_manifest.json").read_text(encoding="utf-8")
    )
    return [chunk["chunk_id"] for chunk in manifest["chunks"]]


def test_course_create_extracts_text_files_and_zip_members(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "topic.md").write_text("# Topic\n\nSome useful content.\n", encoding="utf-8")
    with zipfile.ZipFile(materials / "notes.zip", "w") as archive:
        archive.writestr("topic.md", "# Topic\n\nSome useful content.\n")
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me the material",
        "--context",
        str(materials),
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    extracted_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((course_root / "extracted_sources").rglob("*.txt"))
    )
    assert "Some useful content" in extracted_text

    manifest = json.loads(
        (course_root / "source_index" / "chunk_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["chunk_count"] == 2
    assert any(chunk["source_ref"] == "notes.zip!topic.md" for chunk in manifest["chunks"])


def test_chunk_ids_are_stable_across_repeated_runs(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "topic.md").write_text("# Topic\n\nSome useful content.\n", encoding="utf-8")

    first = run_aiu(
        "course",
        "create",
        "Teach me the material",
        "--context",
        str(materials),
        "--output",
        str(tmp_path / "course-a"),
        "--init-only",
        cwd=tmp_path,
    )
    second = run_aiu(
        "course",
        "create",
        "Teach me the material",
        "--context",
        str(materials),
        "--output",
        str(tmp_path / "course-b"),
        "--init-only",
        cwd=tmp_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert chunk_ids(tmp_path / "course-a") == chunk_ids(tmp_path / "course-b")


def test_pdf_and_images_are_recorded_as_skipped_placeholders(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "paper.pdf").write_bytes(b"%PDF-1.4")
    (materials / "diagram.png").write_bytes(b"\x89PNG\r\n")

    result = run_aiu(
        "course",
        "create",
        "Teach me the material",
        "--context",
        str(materials),
        "--output",
        str(tmp_path / "course"),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    source_manifest = json.loads(
        (tmp_path / "course" / "source_manifest.json").read_text(encoding="utf-8")
    )

    statuses = {source["path_or_url"]: source for source in source_manifest["sources"]}
    assert statuses["paper.pdf"]["extraction_status"] == "skipped"
    assert statuses["diagram.png"]["extraction_status"] == "skipped"
    assert "not implemented yet" in statuses["paper.pdf"]["errors"][0]
