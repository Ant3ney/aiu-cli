from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aiu.ingest import inventory_context_paths


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


def test_course_create_inventories_context_and_honors_aiuignore(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "a.txt").write_text("hello\n", encoding="utf-8")
    (materials / ".aiuignore").write_text("*.skip\n", encoding="utf-8")
    (materials / "b.skip").write_text("ignored\n", encoding="utf-8")
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me from files",
        "--context",
        str(materials),
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    source_manifest = json.loads((course_root / "source_manifest.json").read_text(encoding="utf-8"))
    ingest_report = json.loads((course_root / "ingest_report.json").read_text(encoding="utf-8"))

    assert [source["path_or_url"] for source in source_manifest["sources"]] == ["a.txt"]
    assert source_manifest["sources"][0]["extraction_status"] == "extracted"
    assert ingest_report["accepted_count"] == 1
    assert ingest_report["ignored_count"] == 1
    assert ingest_report["ignored"][0]["path"] == "b.skip"


def test_inventory_honors_gitignore_and_explicit_excludes(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    subdir = materials / "sub"
    subdir.mkdir(parents=True)
    (materials / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (materials / "keep.md").write_text("# Keep\n", encoding="utf-8")
    (materials / "ignored.tmp").write_text("ignore\n", encoding="utf-8")
    (subdir / "drop.txt").write_text("drop\n", encoding="utf-8")

    result = inventory_context_paths([str(materials)], excludes=["sub/*"])

    assert [source.path_or_url for source in result.sources] == ["keep.md"]
    assert sorted(item["path"] for item in result.ignored) == ["ignored.tmp", "sub/drop.txt"]


def test_inventory_skips_unsupported_files_without_crashing(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "keep.txt").write_text("keep\n", encoding="utf-8")
    (materials / "skip.exe").write_bytes(b"\x00\x01")

    result = inventory_context_paths([str(materials)])

    assert [source.path_or_url for source in result.sources] == ["keep.txt"]
    assert result.skipped == [{"path": "skip.exe", "reason": "unsupported file type"}]
