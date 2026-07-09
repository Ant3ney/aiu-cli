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
    assert "Source focus:" in syllabus
    assert "High-Value Source Chunks" in reading_list
    assert state["stages"]["research"]["status"] == "complete"


def test_context_backed_syllabus_teaches_research_without_raw_prompt_leaks(
    tmp_path: Path,
) -> None:
    showdown = tmp_path / "pokemon-showdown-master"
    firered = tmp_path / "pokefirered-master"
    (showdown / "sim").mkdir(parents=True)
    (showdown / "data").mkdir()
    (firered / "src").mkdir(parents=True)
    (firered / "data" / "maps" / "PalletTown").mkdir(parents=True)
    (showdown / "sim" / "battle.ts").write_text(
        "export class Battle { queue; prng; makeChoices() { return this.queue; } }\n"
        "BattleStream resolves turns with deterministic protocol output.\n",
        encoding="utf-8",
    )
    (showdown / "data" / "moves.ts").write_text(
        "export const Moves = { tackle: {basePower: 40, onHit() {}} };\n",
        encoding="utf-8",
    )
    (firered / "src" / "battle_setup.c").write_text(
        "void DoBattleTransition(void) {}\nvoid BattleSetup_StartTrainerBattle(void) {}\n",
        encoding="utf-8",
    )
    (firered / "data" / "maps" / "PalletTown" / "map.json").write_text(
        '{"object_events": [], "warp_events": [], "coord_events": [], "bg_events": []}\n',
        encoding="utf-8",
    )
    course_root = tmp_path / "course"
    prompt = (
        "Help me understand the tecnical architecture of data-driven creature-collector RPG "
        "architecture. pokemon showdown recreates the battle system. pokefirered is a direct "
        "soucce for how these games work. Ensure we undersand overworld progression too."
    )

    result = run_aiu(
        "course",
        "create",
        prompt,
        "--provider",
        "fake",
        "--weeks",
        "4",
        "--lectures-per-week",
        "1",
        "--lecture-hours",
        "0.25",
        "--context",
        str(showdown),
        "--context",
        str(firered),
        "--output",
        str(course_root),
        "--generate-until",
        "syllabus",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    syllabus = (course_root / "syllabus" / "syllabus.md").read_text(encoding="utf-8")
    blueprint = json.loads((course_root / "course_blueprint.json").read_text(encoding="utf-8"))

    assert "tecnical" not in syllabus
    assert "soucce" not in syllabus
    assert "undersand" not in syllabus
    assert prompt not in syllabus
    assert "Pokemon Showdown" in syllabus or "pokemon-showdown-master" in syllabus
    assert "FireRed" in syllabus or "pokefirered-master" in syllabus
    assert "Source focus:" in syllabus
    assert "pokemon-showdown-master/sim" in syllabus
    assert "pokefirered-master/data" in syllabus
    assert all("tecnical" not in week["title"].lower() for week in blueprint["week_plan"])


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
