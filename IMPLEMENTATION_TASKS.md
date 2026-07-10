# AI University CLI Implementation Tasks

This is an ordered build plan for the CLI/core engine described in
`AI_University_CLI_Core_Engine_PRD.md`.

Assumption: implement the CLI as a Python 3.11+ package named `aiu`, with
test coverage using `pytest`. Use deterministic fake provider behavior for
most tests so local verification does not require paid model calls.

Each task should leave the repo in a working state. Do not move to the next
task until the verification plan for the current task passes.

## Task 1 - Scaffold the Python CLI Package

Goal: create a runnable CLI skeleton with packaging, formatting, and tests.

Implementation plan:

- Add `pyproject.toml` with package metadata, console script `aiu`, runtime
  dependencies, and test dependencies.
- Create `src/aiu/` with modules for CLI entry, project paths, config models,
  logging, and version metadata.
- Create `tests/` with a smoke test for `aiu --help`.
- Add a short `README.md` with local setup and command examples.

Expected CLI behavior:

- `aiu --help` exits 0 and shows top-level command groups.
- `aiu --version` exits 0.

Verification:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
aiu --help
aiu --version
pytest
```

Pass criteria:

- Help/version commands work from the installed console script.
- Test suite passes.
- No generated project files are created by help/version commands.

## Task 2 - Implement Project Initialization

Goal: create a valid empty AI University course project.

Implementation plan:

- Implement `aiu init --output <course-root>`.
- Create the PRD-required directory layout:
  `logs/`, `artifacts/`, `source_index/`, `extracted_sources/`, `syllabus/`,
  `lectures/`, `labs/`, `homework/`, `quizzes/`, `exams/`, `projects/`,
  `rubrics/`, `answer_keys/`, `study_guides/`, `vr_handoff/`, and `exports/`.
- Write `course.yaml` and `manifest.json`.
- Use stable generated IDs and ISO timestamps.
- Refuse to overwrite an existing non-empty project unless an explicit
  `--force` option is supplied.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu init --output "$tmpdir/course"
find "$tmpdir/course" -maxdepth 2 -type d | sort
python -m json.tool "$tmpdir/course/manifest.json"
test -f "$tmpdir/course/course.yaml"
pytest
```

Pass criteria:

- Required files and directories exist.
- `manifest.json` is valid JSON and references `course.yaml`.
- Re-running without `--force` fails safely.
- Re-running with `--force` behaves exactly as documented.

## Task 3 - Implement Prompt Intake

Goal: accept learning prompts from argument, file, or stdin and store them in
the project.

Implementation plan:

- Add `aiu course create` with prompt intake only; generation can still be a
  stub in this task.
- Support:
  `aiu course create "Teach me X" --output <dir>`
  `aiu course create --prompt <prompt.md> --output <dir>`
  `echo "Teach me X" | aiu course create --stdin --output <dir>`
- Write `prompt.md`.
- Update `manifest.json` with `prompt_ref`, settings, and prompt checksum.
- Validate that exactly one prompt source is used.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me distributed systems" --output "$tmpdir/course" --init-only
test "$(cat "$tmpdir/course/prompt.md")" = "Teach me distributed systems"
python -m json.tool "$tmpdir/course/manifest.json"

printf "Teach me compilers\n" | aiu course create --stdin --output "$tmpdir/stdin-course" --init-only
test -f "$tmpdir/stdin-course/prompt.md"
pytest
```

Pass criteria:

- All three prompt sources work.
- Invalid combinations return non-zero with a clear error.
- Prompt text is preserved exactly enough for user review.

## Task 4 - Add Typed Schemas and Artifact Store

Goal: define and validate the core data objects before generation logic grows.

Implementation plan:

- Add typed models for `CourseManifest`, `SourceManifest`, `CourseBlueprint`,
  `LectureSession`, `LabSession`, `Assessment`, `VRHandoffCue`, and
  `ValidationReport`.
- Add an artifact store helper for atomic JSON/YAML/Markdown writes.
- Ensure JSON output is stable: sorted keys where practical, deterministic
  paths, and readable indentation.
- Add schema/unit tests for required fields and invalid data.

Verification:

```bash
pytest tests/test_models.py tests/test_artifact_store.py
```

Pass criteria:

- Required-field validation catches invalid objects.
- Atomic writes do not leave partial files on simulated failure.
- Manifest paths are portable and use forward-slash relative paths in JSON.

## Task 5 - Implement Auth and Provider Adapter Interfaces

Goal: add provider configuration without making real model calls yet.

Implementation plan:

- Define a provider adapter interface with methods for generation, streaming
  optional progress, usage accounting, retries, and capability metadata.
- Implement a deterministic `fake` provider used by tests and local dry runs.
- Add config support for an OpenAI-compatible API key via environment variable
  reference, not raw secret storage.
- Implement:
  `aiu auth login --provider fake`
  `aiu auth login --provider openai --api-key-env OPENAI_API_KEY`
  `aiu auth status`
- Ensure generated course artifacts never contain secret values.

Verification:

```bash
aiu auth login --provider fake
aiu auth status
OPENAI_API_KEY=dummy aiu auth login --provider openai --api-key-env OPENAI_API_KEY
rg "dummy|OPENAI_API_KEY=.*" .
pytest
```

Pass criteria:

- Auth status reports configured providers without printing secrets.
- Fake provider can be selected in course commands.
- Tests prove raw secret values are not written into project artifacts.

## Task 6 - Implement Local Context Inventory

Goal: record every user-supplied source path with metadata.

Implementation plan:

- Add `--context <path>` to `aiu course create`, repeatable.
- Support files and directories recursively.
- Honor `.gitignore`, `.aiuignore`, and explicit `--exclude <glob>` patterns.
- Write `source_manifest.json` and `ingest_report.json`.
- Record relative path, type, size, checksum, status, and errors.
- Skip unsupported or unreadable files gracefully.

Verification:

```bash
tmpdir="$(mktemp -d)"
mkdir -p "$tmpdir/materials/sub"
printf "hello\n" > "$tmpdir/materials/a.txt"
printf "*.skip\n" > "$tmpdir/materials/.aiuignore"
printf "ignored\n" > "$tmpdir/materials/b.skip"
aiu course create "Teach me from files" --context "$tmpdir/materials" --output "$tmpdir/course" --init-only
python -m json.tool "$tmpdir/course/source_manifest.json"
python -m json.tool "$tmpdir/course/ingest_report.json"
rg "a.txt" "$tmpdir/course/source_manifest.json"
! rg "b.skip" "$tmpdir/course/source_manifest.json"
pytest
```

Pass criteria:

- All accepted files appear once in the source manifest.
- Ignored files are absent or recorded as ignored according to the documented
  behavior.
- Corrupt/unreadable inputs do not crash the whole command.

## Task 7 - Implement Text Extraction and Chunking

Goal: turn readable local context into extracted text and chunk manifests.

Implementation plan:

- Extract text from plain text, Markdown, JSON, YAML, CSV, and common source
  code files.
- Add archive support for zip files, preserving original archive/source
  relationship in metadata.
- For PDFs and images, add safe placeholder handling if full extraction is not
  implemented yet: record skipped or pending with clear reasons.
- Chunk extracted text with stable chunk IDs and source references.
- Write `extracted_sources/`, `source_index/chunk_manifest.json`, and a simple
  searchable local index.

Verification:

```bash
tmpdir="$(mktemp -d)"
mkdir "$tmpdir/materials"
printf "# Topic\n\nSome useful content.\n" > "$tmpdir/materials/topic.md"
(cd "$tmpdir/materials" && zip notes.zip topic.md >/dev/null)
aiu course create "Teach me the material" --context "$tmpdir/materials" --output "$tmpdir/course" --init-only
python -m json.tool "$tmpdir/course/source_index/chunk_manifest.json"
rg "Some useful content" "$tmpdir/course/extracted_sources"
pytest
```

Pass criteria:

- Text files and zip-contained text files are extracted.
- Chunk IDs are stable across repeated runs with the same inputs.
- Unsupported extraction cases are recorded in the ingest report.

## Task 8 - Generate Learning Intent and Course Blueprint

Goal: produce a course plan using the fake provider and persist it in Markdown
and JSON.

Implementation plan:

- Implement intent analysis fields from the PRD.
- Implement `aiu course plan <course-root>`.
- Generate `intent_analysis.json`, `course_blueprint.json`,
  `course_blueprint.md`, and `schedule.json`.
- Use settings for `--weeks`, `--lectures-per-week`, `--lecture-hours`,
  `--level`, and `--lab-policy`.
- Ensure default 24 weeks and 2 lectures/week.
- With fake provider, generate deterministic blueprint content.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me machine learning" --provider fake --output "$tmpdir/course" --init-only
aiu course plan "$tmpdir/course"
python -m json.tool "$tmpdir/course/course_blueprint.json"
python -m json.tool "$tmpdir/course/schedule.json"
python - "$tmpdir/course/schedule.json" <<'PY'
import json, sys
schedule = json.load(open(sys.argv[1]))
lectures = [x for x in schedule["items"] if x["type"] == "lecture"]
assert len(lectures) == 48, len(lectures)
PY
pytest
```

Pass criteria:

- Blueprint contains title, outcomes, prerequisites, modules, week plan,
  assessment plan, source usage plan, and lab policy.
- Default schedule has 48 lecture entries.
- Custom week and lecture counts produce matching schedules.

## Task 9 - Implement Approval Gate

Goal: prevent expensive generation until the course plan is approved or `--yes`
is supplied.

Implementation plan:

- Implement `aiu course approve <course-root>`.
- Store `approved_course_blueprint.json` and approval metadata.
- Make `aiu course generate <course-root>` refuse to run without approval in
  interactive/default mode.
- Allow `aiu course generate <course-root> --yes` to approve and generate in
  one command.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me databases" --provider fake --output "$tmpdir/course" --init-only
aiu course plan "$tmpdir/course"
! aiu course generate "$tmpdir/course"
aiu course approve "$tmpdir/course"
aiu course generate "$tmpdir/course" --dry-run
test -f "$tmpdir/course/approved_course_blueprint.json"
pytest
```

Pass criteria:

- Generation is blocked until approval unless `--yes` is used.
- Approval writes an immutable snapshot of the blueprint used for generation.
- Re-approval behavior is documented and tested.

## Task 10 - Implement Checkpointing, Status, and Resume Core

Goal: make long-running generation resumable before adding all generators.

Implementation plan:

- Add a checkpoint/state file, for example `.aiu/state.json`.
- Track stages and artifact-level status: pending, running, complete, failed,
  skipped.
- Implement `aiu course status <course-root>`.
- Add resume behavior that skips completed artifacts unless regeneration is
  explicitly requested.
- Add test hooks or fake provider options to simulate interruption/failure.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me operating systems" --provider fake --output "$tmpdir/course" --yes --generate-until blueprint
aiu course status "$tmpdir/course"
python -m json.tool "$tmpdir/course/.aiu/state.json"
pytest tests/test_resume.py
```

Pass criteria:

- Status clearly shows completed, pending, and failed stages.
- Simulated failure can be resumed without rewriting completed artifacts.
- Interrupted writes never corrupt valid completed JSON files.

## Task 11 - Generate Syllabus and Course-Level Artifacts

Goal: produce the top-level human-facing course materials.

Implementation plan:

- Generate:
  `syllabus/syllabus.md`
  `syllabus/grading_policy.md`
  `syllabus/reading_list.md`
  `study_guides/course_overview.md`
- Update the manifest artifact index.
- Include source references when source chunks exist.
- Include machine-readable sidecar metadata or consolidated artifact index
  entries.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me algorithms" --provider fake --output "$tmpdir/course" --yes
aiu course generate "$tmpdir/course" --stage syllabus
test -f "$tmpdir/course/syllabus/syllabus.md"
test -f "$tmpdir/course/syllabus/grading_policy.md"
test -f "$tmpdir/course/syllabus/reading_list.md"
python -m json.tool "$tmpdir/course/manifest.json"
pytest
```

Pass criteria:

- Syllabus artifacts exist and reference the approved blueprint.
- Manifest artifact index includes all generated files.
- Re-running the same stage is idempotent unless forced.

## Task 12 - Generate Lecture Artifacts and VR Lecture Cues

Goal: generate scheduled lecture Markdown, JSON metadata, and VR handoff cues.

Implementation plan:

- For every scheduled lecture, write:
  `lectures/week_XX/day_YY.md`
  `lectures/week_XX/day_YY.json`
  `vr_handoff/lecture_scene_cues/<lecture_id>.json`
- Include required lecture fields: ID, week, day, title, objectives,
  transcript, source refs, estimated duration, and VR cues.
- Fake provider output may be short but structurally complete; real provider
  output can later expand transcript length.
- Checkpoint after each lecture.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me networking" --provider fake --output "$tmpdir/course" --yes
aiu course generate "$tmpdir/course" --stage lectures
find "$tmpdir/course/lectures" -name "*.md" | wc -l
find "$tmpdir/course/lectures" -name "*.json" | wc -l
find "$tmpdir/course/vr_handoff/lecture_scene_cues" -name "*.json" | wc -l
pytest
```

Pass criteria:

- Default course produces 48 lecture Markdown files and 48 lecture JSON files.
- Every lecture JSON validates against the `LectureSession` schema.
- Every lecture has at least one VR cue or explicitly documented empty cue
  policy.

## Task 13 - Generate Labs or Lab Alternatives

Goal: implement lab policy behavior.

Implementation plan:

- Support `lab-policy` values `auto`, `always`, and `never`.
- Generate weekly labs when policy is `always`.
- Generate no labs when policy is `never`; generate alternate recitation,
  seminar, case-study, or workshop activities instead.
- In `auto`, include a written rationale in the blueprint and generated
  artifacts.
- Write lab metadata and `vr_handoff/lab_scene_cues/`.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me physics" --provider fake --lab-policy always --output "$tmpdir/labs" --yes
aiu course generate "$tmpdir/labs" --stage labs
test "$(find "$tmpdir/labs/labs" -name "*.md" | wc -l)" -eq 24

aiu course create "Teach me history" --provider fake --lab-policy never --output "$tmpdir/no-labs" --yes
aiu course generate "$tmpdir/no-labs" --stage labs
test "$(find "$tmpdir/no-labs/labs" -name "*.md" | wc -l)" -eq 0
pytest
```

Pass criteria:

- `always` creates one lab per week.
- `never` creates no lab files and does create appropriate alternative
  activity artifacts.
- `auto` records its decision and is deterministic under the fake provider.

## Task 14 - Generate Homework, Quizzes, Exams, Projects, Rubrics, and Answer Keys

Goal: complete the core academic artifact set.

Implementation plan:

- Generate weekly homework and quizzes.
- Generate midterm and final exams or equivalent cumulative assessments.
- Generate project artifacts when appropriate for the blueprint.
- Generate rubrics and answer keys for every graded artifact.
- Ensure each assessment maps to learning objectives.
- Update manifest and checkpoint state after each artifact.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me software engineering" --provider fake --output "$tmpdir/course" --yes
aiu course generate "$tmpdir/course" --stage assessments
test "$(find "$tmpdir/course/homework" -name "*.md" | wc -l)" -ge 24
test "$(find "$tmpdir/course/quizzes" -name "*.md" | wc -l)" -ge 12
test -f "$tmpdir/course/exams/midterm.md"
test -f "$tmpdir/course/exams/final.md"
test "$(find "$tmpdir/course/rubrics" -name "*.md" | wc -l)" -gt 0
test "$(find "$tmpdir/course/answer_keys" -name "*.md" | wc -l)" -gt 0
pytest
```

Pass criteria:

- Every graded artifact has a rubric and answer key.
- Assessments reference course objectives.
- Manifest lists all generated academic artifacts.

## Task 15 - Implement Validation Engine

Goal: detect missing, inconsistent, or invalid course packages.

Implementation plan:

- Implement `aiu course validate <course-root>`.
- Validate required files, JSON schemas, schedule/artifact consistency,
  lecture counts, lab policy, broken references, citation coverage, VR handoff
  files, and objective/assessment mappings.
- Write `validation_report.json` and `warnings.md`.
- Return non-zero when validation status is `fail`.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me cryptography" --provider fake --output "$tmpdir/course" --yes
aiu course generate "$tmpdir/course"
aiu course validate "$tmpdir/course"
python -m json.tool "$tmpdir/course/validation_report.json"
rm "$tmpdir/course/schedule.json"
! aiu course validate "$tmpdir/course"
pytest tests/test_validation.py
```

Pass criteria:

- Valid fake-provider course passes or warns only for documented limitations.
- Deleting a required artifact causes validation failure.
- Report contains actionable failures and artifact counts.

## Task 16 - Implement End-to-End Course Create/Generate Flow

Goal: make the MVP happy path work with one command.

Implementation plan:

- Support:
  `aiu course create "Teach me X" --provider fake --output <dir> --yes`
- The command should initialize, store prompt, ingest context if provided,
  plan, approve when `--yes` is present, generate all MVP artifacts, validate,
  and exit with the right status.
- Keep subcommands available for separate plan/generate/validate flows.
- Add progress logging to `logs/`.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me artificial intelligence" --provider fake --output "$tmpdir/course" --yes
aiu course status "$tmpdir/course"
aiu course validate "$tmpdir/course"
test -f "$tmpdir/course/validation_report.json"
test -f "$tmpdir/course/logs/aiu.log"
pytest
```

Pass criteria:

- A complete fake-provider course is generated from one command.
- Validation runs automatically or is clearly reported as the next required
  command.
- Logs include stage starts, completions, warnings, and failures.

## Task 17 - Implement Selective Regeneration

Goal: regenerate selected artifacts without rebuilding the whole course.

Implementation plan:

- Implement:
  `aiu course regenerate <course-root> --artifact lecture:w08:d01`
  `aiu course generate <course-root> --from week:10 --to week:12`
- Use the approved blueprint and dependency graph.
- Preserve completed unrelated artifacts.
- Mark regenerated artifacts in state and manifest metadata.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me compilers" --provider fake --output "$tmpdir/course" --yes
before="$(sha256sum "$tmpdir/course/lectures/week_01/day_01.md")"
aiu course regenerate "$tmpdir/course" --artifact lecture:w08:d01
after="$(sha256sum "$tmpdir/course/lectures/week_01/day_01.md")"
test "$before" = "$after"
aiu course validate "$tmpdir/course"
pytest tests/test_regenerate.py
```

Pass criteria:

- Targeted regeneration updates only the selected artifact and dependent
  indexes/reports.
- Unrelated artifact checksums remain unchanged.
- Validation still passes after regeneration.

## Task 18 - Implement Exports and VR Package Manifest

Goal: package generated materials for downstream use.

Implementation plan:

- Implement `aiu course export <course-root> --format markdown,json,vr`.
- Generate `exports/markdown/`, `exports/json/`, and/or `exports/vr/`.
- Write `vr_handoff/course_runtime_manifest.json`.
- Include scene cue indexes, lecture/lab references, schedule, prerequisite
  hooks, and interaction anchors.
- Support redacting absolute local paths in exported manifests.

Verification:

```bash
tmpdir="$(mktemp -d)"
aiu course create "Teach me data science" --provider fake --output "$tmpdir/course" --yes
aiu course export "$tmpdir/course" --format markdown,json,vr
test -f "$tmpdir/course/vr_handoff/course_runtime_manifest.json"
test -d "$tmpdir/course/exports/markdown"
test -d "$tmpdir/course/exports/json"
test -d "$tmpdir/course/exports/vr"
pytest tests/test_export.py
```

Pass criteria:

- Requested export formats are created.
- VR runtime manifest validates and references existing cue files.
- Exported files do not leak raw secrets or unwanted absolute paths.

## Task 19 - Add Real OpenAI-Compatible Provider

Goal: connect the adapter interface to a real provider while preserving fake
provider tests.

Implementation plan:

- Implement the OpenAI-compatible provider behind the adapter interface.
- Read credentials from configured environment variable names only.
- Add retry and rate-limit handling.
- Track provider usage metadata where available.
- Add `--dry-run` and fake provider defaults for CI safety.
- Keep real-provider tests behind an opt-in environment flag.

Verification:

```bash
pytest

# Optional integration test, only when credentials are intentionally available:
AIU_RUN_OPENAI_INTEGRATION=1 OPENAI_API_KEY=... pytest tests/integration/test_openai_provider.py
```

Pass criteria:

- Unit tests do not require network or credentials.
- Integration test can generate a small blueprint with real credentials.
- Rate-limit/auth failures are checkpointed and reported without corrupting the
  course project.

## Task 20 - Hardening, Security, and Release Readiness

Goal: make the CLI reliable enough for repeated manual testing.

Implementation plan:

- Audit generated files for secret leakage.
- Add cross-platform path tests.
- Add cancellation handling for long-running generation.
- Add clear exit codes for validation failure, auth failure, user cancellation,
  bad input, and provider errors.
- Keep long-running CLI output readable across terminal sizes: group progress
  by stage, wrap long artifact paths/details/previews, and preserve the full
  event stream in `logs/aiu.log`.
- Add CI workflow if this repo will be pushed to GitHub.
- Update README with MVP workflows and troubleshooting.

Verification:

```bash
pytest
aiu --help
aiu course create --help
aiu course validate --help
aiu auth --help
```

Pass criteria:

- All tests pass.
- Help output documents the stable workflow.
- The CLI can generate, validate, resume, regenerate, and export a fake-provider
  course repeatedly on a clean checkout.
