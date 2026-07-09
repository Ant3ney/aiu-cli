"""Course package validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from aiu.artifact_store import ArtifactStore
from aiu.config import LabPolicy
from aiu.course_rails import RAILS_REF, RAILS_SCHEMA_NAME, RAILS_SCHEMA_VERSION
from aiu.lecture_quality import minimum_transcript_words, transcript_word_count
from aiu.models import (
    CourseBlueprint,
    CourseManifest,
    LabSession,
    LectureSession,
    ValidationCheck,
    ValidationReport,
    ValidationStatus,
)
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage, fail_stage, start_stage


class CourseValidationError(ValueError):
    """Raised when validation completes with failing status."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__("Course validation failed.")


def validate_course(course_root: str | Path) -> ValidationReport:
    """Validate generated course package structure and schemas."""

    store = ArtifactStore(course_root)
    start_stage(course_root, "validation")
    checks: list[ValidationCheck] = []
    warnings: list[str] = []
    failures: list[str] = []
    schema_errors: list[str] = []

    required_files = [
        "manifest.json",
        "course.yaml",
        "prompt.md",
        "course_blueprint.json",
        "approved_course_blueprint.json",
        "schedule.json",
        RAILS_REF,
    ]
    for relative_path in required_files:
        _check_file(store, relative_path, checks, failures)

    manifest = _validate_json_model(store, "manifest.json", CourseManifest, schema_errors)
    blueprint = _validate_json_model(
        store, "approved_course_blueprint.json", CourseBlueprint, schema_errors
    )
    schedule = _read_json_if_exists(store, "schedule.json")

    if manifest is not None and schedule is not None:
        _validate_schedule(store, manifest, schedule, checks, failures)
        _validate_rails(store, manifest, checks, failures, schema_errors)
    if blueprint is not None:
        _validate_labs(store, blueprint, checks, failures)
        _validate_assessments(store, checks, failures, schema_errors)
        _validate_lecture_files(store, schedule or {}, checks, failures, schema_errors)
    _validate_citations(store, warnings)

    artifact_counts = _artifact_counts(store)
    citation_coverage = _citation_coverage(store)
    status = (
        ValidationStatus.FAIL
        if failures or schema_errors
        else ValidationStatus.WARN
        if warnings
        else ValidationStatus.PASS
    )
    report = ValidationReport(
        status=status,
        checks=checks,
        warnings=warnings,
        failures=failures,
        artifact_counts=artifact_counts,
        citation_coverage=citation_coverage,
        schema_errors=schema_errors,
    )
    store.write_json("validation_report.json", report)
    store.write_markdown("warnings.md", _warnings_markdown(report))
    update_manifest_artifacts(
        course_root,
        [
            ("validation_report", "json", "validation_report.json"),
            ("validation_warnings", "markdown", "warnings.md"),
        ],
    )
    if status == ValidationStatus.FAIL:
        fail_stage(course_root, "validation", "; ".join([*failures, *schema_errors]))
        raise CourseValidationError(report)
    complete_stage(course_root, "validation", ["validation_report.json", "warnings.md"])
    return report


def _check_file(
    store: ArtifactStore,
    relative_path: str,
    checks: list[ValidationCheck],
    failures: list[str],
) -> None:
    exists = store.course_path(relative_path).is_file()
    status = ValidationStatus.PASS if exists else ValidationStatus.FAIL
    checks.append(
        ValidationCheck(
            check_id=f"required:{relative_path}",
            status=status,
            message=f"Required file {'exists' if exists else 'is missing'}: {relative_path}",
            artifact_ref=relative_path,
        )
    )
    if not exists:
        failures.append(f"Missing required file: {relative_path}")


def _validate_json_model(
    store: ArtifactStore,
    relative_path: str,
    model: type[Any],
    schema_errors: list[str],
) -> Any | None:
    path = store.course_path(relative_path)
    if not path.exists():
        return None
    try:
        return model.model_validate(store.read_json(relative_path))
    except (OSError, ValueError, PydanticValidationError) as exc:
        schema_errors.append(f"{relative_path}: {exc}")
        return None


def _read_json_if_exists(store: ArtifactStore, relative_path: str) -> dict[str, Any] | None:
    if not store.course_path(relative_path).exists():
        return None
    return store.read_json(relative_path)


def _validate_schedule(
    store: ArtifactStore,
    manifest: CourseManifest,
    schedule: dict[str, Any],
    checks: list[ValidationCheck],
    failures: list[str],
) -> None:
    lectures = [item for item in schedule.get("items", []) if item.get("type") == "lecture"]
    expected = manifest.settings.weeks * manifest.settings.lectures_per_week
    ok = len(lectures) == expected
    checks.append(
        ValidationCheck(
            check_id="schedule:lecture_count",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            message=f"Schedule has {len(lectures)} lecture(s); expected {expected}.",
        )
    )
    if not ok:
        failures.append(
            f"Schedule lecture count mismatch: expected {expected}, found {len(lectures)}"
        )

    lecture_json_files = list((store.root / "lectures").rglob("*.json"))
    ok_files = len(lecture_json_files) == expected
    checks.append(
        ValidationCheck(
            check_id="lectures:file_count",
            status=ValidationStatus.PASS if ok_files else ValidationStatus.FAIL,
            message=f"Found {len(lecture_json_files)} lecture JSON file(s); expected {expected}.",
        )
    )
    if not ok_files:
        failures.append(
            "Lecture JSON file count mismatch: "
            f"expected {expected}, found {len(lecture_json_files)}"
        )


def _validate_lecture_files(
    store: ArtifactStore,
    schedule: dict[str, Any],
    checks: list[ValidationCheck],
    failures: list[str],
    schema_errors: list[str],
) -> None:
    duration_by_lecture_id: dict[str, float] = {}
    for item in schedule.get("items", []):
        if item.get("type") != "lecture" or item.get("id") is None:
            continue
        if item.get("duration_hours") is None:
            continue
        try:
            duration_by_lecture_id[str(item["id"])] = float(item["duration_hours"])
        except (TypeError, ValueError):
            continue
    short_transcripts: list[str] = []

    for path in sorted((store.root / "lectures").rglob("*.json")):
        try:
            lecture = LectureSession.model_validate(
                store.read_json(path.relative_to(store.root).as_posix())
            )
        except (OSError, ValueError, PydanticValidationError) as exc:
            schema_errors.append(f"{path.relative_to(store.root).as_posix()}: {exc}")
            continue
        cue_path = store.course_path(f"vr_handoff/lecture_scene_cues/{lecture.lecture_id}.json")
        if not cue_path.exists():
            failures.append(f"Missing VR cue file for lecture: {lecture.lecture_id}")
        duration_hours = duration_by_lecture_id.get(
            lecture.lecture_id, lecture.estimated_duration
        )
        required_words = minimum_transcript_words(duration_hours)
        actual_words = transcript_word_count(lecture.transcript)
        if actual_words < required_words:
            short_transcripts.append(
                f"{lecture.lecture_id} has {actual_words} transcript words; "
                f"required {required_words}."
            )

    scheduled_ids = {
        item.get("id") for item in schedule.get("items", []) if item.get("type") == "lecture"
    }
    cue_ids = {
        path.stem for path in (store.root / "vr_handoff" / "lecture_scene_cues").glob("*.json")
    }
    missing = sorted(str(lecture_id) for lecture_id in scheduled_ids - cue_ids)
    checks.append(
        ValidationCheck(
            check_id="vr:lecture_cues",
            status=ValidationStatus.PASS if not missing else ValidationStatus.FAIL,
            message="Lecture VR cue files are present."
            if not missing
            else f"Missing lecture cues: {missing}",
        )
    )
    failures.extend(f"Missing lecture VR cue: {lecture_id}" for lecture_id in missing)
    checks.append(
        ValidationCheck(
            check_id="lectures:transcript_length",
            status=ValidationStatus.PASS if not short_transcripts else ValidationStatus.FAIL,
            message="Lecture transcripts meet configured duration targets."
            if not short_transcripts
            else f"{len(short_transcripts)} lecture transcript(s) are too short.",
        )
    )
    failures.extend(f"Short lecture transcript: {failure}" for failure in short_transcripts)


def _validate_labs(
    store: ArtifactStore,
    blueprint: CourseBlueprint,
    checks: list[ValidationCheck],
    failures: list[str],
) -> None:
    week_count = len(blueprint.week_plan)
    lab_files = list((store.root / "labs").glob("*.md"))
    if blueprint.lab_policy == LabPolicy.NEVER:
        alternatives = list((store.root / "artifacts" / "activities").glob("*.md"))
        ok = not lab_files and len(alternatives) == week_count
        message = f"Lab policy never has {len(alternatives)} alternative activity file(s)."
    else:
        lab_json_files = list((store.root / "labs").glob("*.json"))
        ok = len(lab_files) == week_count and len(lab_json_files) == week_count
        message = f"Found {len(lab_files)} lab file(s); expected {week_count}."
        for path in lab_json_files:
            try:
                LabSession.model_validate(store.read_json(path.relative_to(store.root).as_posix()))
            except (OSError, ValueError, PydanticValidationError) as exc:
                failures.append(f"Invalid lab JSON {path.name}: {exc}")
    checks.append(
        ValidationCheck(
            check_id="labs:policy",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            message=message,
        )
    )
    if not ok:
        failures.append("Lab artifacts do not match configured lab policy.")


def _validate_assessments(
    store: ArtifactStore,
    checks: list[ValidationCheck],
    failures: list[str],
    schema_errors: list[str],
) -> None:
    assessment_json = [
        *list((store.root / "homework").glob("*.json")),
        *list((store.root / "quizzes").glob("*.json")),
        *list((store.root / "exams").glob("*.json")),
        *list((store.root / "projects").glob("*.json")),
    ]
    missing_links: list[str] = []
    for path in assessment_json:
        relative = path.relative_to(store.root).as_posix()
        try:
            data = store.read_json(relative)
        except OSError as exc:
            schema_errors.append(f"{relative}: {exc}")
            continue
        if not data.get("objectives"):
            missing_links.append(relative)
    ok = bool(assessment_json) and not missing_links
    checks.append(
        ValidationCheck(
            check_id="assessments:objective_mapping",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            message="Assessments map to objectives." if ok else "Some assessments lack objectives.",
        )
    )
    failures.extend(f"Assessment missing objective mapping: {item}" for item in missing_links)
    if not assessment_json:
        failures.append("No assessment JSON artifacts found.")


def _validate_rails(
    store: ArtifactStore,
    manifest: CourseManifest,
    checks: list[ValidationCheck],
    failures: list[str],
    schema_errors: list[str],
) -> None:
    if not store.course_path(RAILS_REF).exists():
        return
    try:
        rails = store.read_json(RAILS_REF)
    except (OSError, ValueError) as exc:
        schema_errors.append(f"{RAILS_REF}: {exc}")
        return

    schema = rails.get("schema", {})
    schema_ok = (
        schema.get("name") == RAILS_SCHEMA_NAME
        and schema.get("version") == RAILS_SCHEMA_VERSION
    )
    checks.append(
        ValidationCheck(
            check_id="rails:schema",
            status=ValidationStatus.PASS if schema_ok else ValidationStatus.FAIL,
            message="Rails schema is supported."
            if schema_ok
            else "Rails schema is missing or unsupported.",
            artifact_ref=RAILS_REF,
        )
    )
    if not schema_ok:
        failures.append("rails.json schema is missing or unsupported.")

    lectures = rails.get("artifact_catalog", {}).get("lectures", [])
    expected_lectures = manifest.settings.weeks * manifest.settings.lectures_per_week
    lecture_count_ok = isinstance(lectures, list) and len(lectures) == expected_lectures
    checks.append(
        ValidationCheck(
            check_id="rails:lecture_catalog",
            status=ValidationStatus.PASS if lecture_count_ok else ValidationStatus.FAIL,
            message=f"Rails catalogs {len(lectures)} lecture(s); expected {expected_lectures}.",
            artifact_ref=RAILS_REF,
        )
    )
    if not lecture_count_ok:
        failures.append(
            f"rails.json lecture catalog mismatch: expected {expected_lectures}, "
            f"found {len(lectures) if isinstance(lectures, list) else 0}"
        )

    day_plan = rails.get("day_by_day_plan", [])
    day_plan_ok = isinstance(day_plan, list) and bool(day_plan)
    checks.append(
        ValidationCheck(
            check_id="rails:day_by_day_plan",
            status=ValidationStatus.PASS if day_plan_ok else ValidationStatus.FAIL,
            message="Rails day-by-day plan is present."
            if day_plan_ok
            else "Rails day-by-day plan is missing.",
            artifact_ref=RAILS_REF,
        )
    )
    if not day_plan_ok:
        failures.append("rails.json day_by_day_plan is missing or empty.")

    missing_refs = _missing_rails_refs(store, rails)
    checks.append(
        ValidationCheck(
            check_id="rails:artifact_refs",
            status=ValidationStatus.PASS if not missing_refs else ValidationStatus.FAIL,
            message="Rails artifact references resolve."
            if not missing_refs
            else f"Rails has missing artifact references: {missing_refs[:5]}",
            artifact_ref=RAILS_REF,
        )
    )
    failures.extend(f"rails.json references missing artifact: {ref}" for ref in missing_refs)


def _validate_citations(store: ArtifactStore, warnings: list[str]) -> None:
    chunk_manifest = store.course_path("source_index/chunk_manifest.json")
    if not chunk_manifest.exists():
        warnings.append("No local source chunks were available for citation coverage.")
        return
    if not store.course_path("context_research.md").exists():
        warnings.append(
            "Local source chunks exist but context_research.md is missing; "
            "source-grounded generation may be shallow."
        )


def _citation_coverage(store: ArtifactStore) -> float:
    lecture_files = list((store.root / "lectures").rglob("*.json"))
    if not lecture_files:
        return 0.0
    with_refs = 0
    for path in lecture_files:
        data = store.read_json(path.relative_to(store.root).as_posix())
        if data.get("source_refs"):
            with_refs += 1
    return with_refs / len(lecture_files)


def _artifact_counts(store: ArtifactStore) -> dict[str, int]:
    return {
        "answer_keys": len(list((store.root / "answer_keys").glob("*.md"))),
        "exams": len(list((store.root / "exams").glob("*.md"))),
        "homework": len(list((store.root / "homework").glob("*.md"))),
        "labs": len(list((store.root / "labs").glob("*.md"))),
        "lectures": len(list((store.root / "lectures").rglob("*.md"))),
        "quizzes": len(list((store.root / "quizzes").glob("*.md"))),
        "rails": 1 if store.course_path(RAILS_REF).is_file() else 0,
        "rubrics": len(list((store.root / "rubrics").glob("*.md"))),
        "vr_lecture_cues": len(
            list((store.root / "vr_handoff" / "lecture_scene_cues").glob("*.json"))
        ),
    }


def _warnings_markdown(report: ValidationReport) -> str:
    lines = [f"# Validation {report.status.value}", ""]
    if report.failures:
        lines.extend(["## Failures", *[f"- {failure}" for failure in report.failures], ""])
    if report.warnings:
        lines.extend(["## Warnings", *[f"- {warning}" for warning in report.warnings], ""])
    if not report.failures and not report.warnings:
        lines.append("No warnings or failures.")
    return "\n".join(lines) + "\n"


def _missing_rails_refs(store: ArtifactStore, rails: Any) -> list[str]:
    missing: list[str] = []
    for ref in _rails_path_refs(rails):
        try:
            path = store.course_path(ref)
        except ValueError:
            missing.append(ref)
            continue
        if not path.exists():
            missing.append(ref)
    return sorted(set(missing))


def _rails_path_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_rails_path_key(str(key)) and isinstance(child, str):
                refs.append(child)
            else:
                refs.extend(_rails_path_refs(child))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_rails_path_refs(item))
    return refs


def _is_rails_path_key(key: str) -> bool:
    return key.endswith("_ref") or key in {
        "approved_blueprint",
        "blueprint",
        "manifest",
        "path",
        "schedule",
    }
