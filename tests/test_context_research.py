from __future__ import annotations

import json
import os
import subprocess
import sys
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


def test_syllabus_preview_builds_context_research_notes(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "battle.md").write_text(
        "# Battle Engine\n\n"
        "Damage formulas, type matchups, status effects, and turn order should anchor "
        "the battle systems portion of the course.\n",
        encoding="utf-8",
    )
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me Pokemon systems design",
        "--provider",
        "fake",
        "--weeks",
        "2",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--context",
        str(materials),
        "--output",
        str(course_root),
        "--generate-until",
        "syllabus",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    research_markdown = (course_root / "context_research.md").read_text(encoding="utf-8")
    research_json = json.loads(
        (course_root / "source_index" / "context_research.json").read_text(encoding="utf-8")
    )
    syllabus = (course_root / "syllabus" / "syllabus.md").read_text(encoding="utf-8")
    reading_list = (course_root / "syllabus" / "reading_list.md").read_text(encoding="utf-8")
    state = json.loads((course_root / ".aiu" / "state.json").read_text(encoding="utf-8"))

    assert "Context Research Notes" in research_markdown
    assert research_json["chunk_count"] >= 1
    assert research_json["idea_chunks"]
    assert "context_research.md" in syllabus
    assert "Source-grounded module" in syllabus
    assert "High-Value Source Chunks" in reading_list
    assert state["stages"]["research"]["status"] == "complete"


def test_fake_lectures_cite_researched_source_chunks(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "battle_engine.md").write_text(
        "# Battle Engine\n\n"
        "The battle engine resolves move priority, type effectiveness, stat stages, "
        "accuracy checks, and status effects in a predictable order.\n",
        encoding="utf-8",
    )
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me Pokemon battle engine architecture",
        "--provider",
        "fake",
        "--weeks",
        "1",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--context",
        str(materials),
        "--output",
        str(course_root),
        "--yes",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    research = json.loads(
        (course_root / "source_index" / "context_research.json").read_text(encoding="utf-8")
    )
    chunk_id = research["idea_chunks"][0]["chunk_id"]
    source_ref = research["idea_chunks"][0]["source_ref"]
    lecture = json.loads(
        (course_root / "lectures" / "week_01" / "day_01.json").read_text(encoding="utf-8")
    )

    assert source_ref in lecture["source_refs"]
    assert "source research packet points us to" in lecture["transcript"]
    assert chunk_id in lecture["transcript"]


def test_multiple_context_directories_keep_project_prefixes(tmp_path: Path) -> None:
    first = tmp_path / "pokefirered-master"
    second = tmp_path / "pokemon-showdown-master"
    first.mkdir()
    second.mkdir()
    (first / "README.md").write_text("Battle engine notes.\n", encoding="utf-8")
    (second / "README.md").write_text("Simulator server notes.\n", encoding="utf-8")
    course_root = tmp_path / "course"

    result = run_aiu(
        "course",
        "create",
        "Teach me Pokemon implementation",
        "--provider",
        "fake",
        "--context",
        str(first),
        "--context",
        str(second),
        "--output",
        str(course_root),
        "--init-only",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    source_manifest = json.loads((course_root / "source_manifest.json").read_text(encoding="utf-8"))
    paths = sorted(source["path_or_url"] for source in source_manifest["sources"])

    assert paths == [
        "pokefirered-master/README.md",
        "pokemon-showdown-master/README.md",
    ]
