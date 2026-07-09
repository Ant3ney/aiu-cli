# AI University CLI/Core Engine PRD

**Product Requirements Document**  
Draft v0.1 - June 27, 2026  
Scope: CLI and core engine only; VR/graphics captured as downstream context

| Field | Value |

| --- | --- |

| Product | AI University |

| Document owner | Product / Engineering |

| Primary deliverable | CLI and core engine that generate a complete university-style course from a learning prompt and optional files/directories |

| Future dependent product | VR/graphics application that consumes structured course artifacts |

| Status | Draft for review |



This PRD turns the initial concept into implementation-ready requirements for the CLI/core engine. The product vision is intentionally broader than the CLI: the engine should eventually feed an immersive VR university experience, but the first build must produce reliable, structured course content from the command line.

## 1. Executive Summary

AI University is a learning-generation system that transforms an education-oriented prompt plus optional user-provided context into a full university-style course. The CLI/core engine is the first product surface. It must accept a prompt, files, images, archives, or directories; configure an AI provider; plan a course; generate all course artifacts; validate quality; and package outputs for future use by a graphic/VR application.

The core engine should not treat the user prompt as a simple chat question. It should assume the user wants to understand a concept deeply enough to benefit from a semester-length course. The engine must expand the prompt into a curriculum with lectures, labs when appropriate, homework, activities, quizzes, tests, rubrics, projects, answer keys, source citations, and metadata that can later drive a simulated university experience.

The CLI MVP must prioritize correctness, resumability, structured output, and future portability. A full course can include dozens of long lecture transcripts and many assessments, so the engine must generate content in stages rather than as a single massive response.

## 2. Product Vision

The long-term vision is a VR university simulator where a learner can sit in lectures, interact with a professor, ask questions in real time, complete labs, receive assignments, and progress through a course. The CLI/core engine is the content factory beneath that experience.

In the CLI phase, the user experience is:

- The user provides a learning prompt, such as "teach me distributed systems from first principles" or "turn this folder of research papers into a course."

- The user optionally attaches or points to context: files, images, zip files, repositories, folders, PDFs, notes, datasets, or other local directories.

- The user selects or configures an AI provider through a Codex subscription, API key, or provider adapter.

- The CLI analyzes the learning goal, inventories sources, creates a course plan, and asks for optional approval before expensive full generation.

- The engine generates a complete course package with semester schedule, lecture transcripts, labs, homework, quizzes, tests, rubrics, projects, and future VR handoff metadata.

## 3. External Integration Context

The implementation should treat MCP as the standard integration layer for tools, context, prompts, and external resources. MCP is an open-source standard for connecting AI applications to external systems, and its official docs describe connections to data sources, tools, and workflows. MCP servers can expose tools, resources, and prompt templates, which aligns with AI University needs such as local file access, retrieval, citation lookup, code execution, and future content pipelines. References are listed at the end of this document.

The OpenAI/Codex provider path should support both subscription-based sign-in and API-key based usage where available. The CLI design should avoid hard-coding one provider and should expose a provider adapter interface so the engine can support Codex, OpenAI API, and other compatible providers over time.

## 4. Goals and Non-Goals

### 4.1 Goals

- Generate a full university-style course from one broad learning prompt and optional source context.

- Support files, images, archives, and local directories as source material without arbitrary product-level size limits.

- Use staged planning and generation so large courses are resumable, inspectable, and recoverable after failures.

- Produce structured artifacts that are useful now in a file system and later in a VR/graphics runtime.

- Support provider authentication and execution via Codex subscription, API key, or future provider adapters.

- Use MCP-compatible tools/resources/prompts for extensible context ingestion, retrieval, research, and generation workflows.

- Include assessments and activities expected in a university course: homework, quizzes, labs, projects, exams, rubrics, answer keys, and practice activities.

- Make generation auditable through logs, citations, source manifests, progress state, cost/usage estimates, and validation reports.

### 4.2 Non-Goals for the CLI MVP

- Real-time VR rendering, avatars, voice synthesis, animation, or graphics engine integration.

- A fully interactive learner runtime or LMS replacement.

- Accreditation, certification, or official university credit.

- Automated grading of user-submitted work, except generation of rubrics, answer keys, and sample solutions.

- Unlimited provider usage. The CLI should not impose arbitrary course-size limits, but provider rate limits, local disk, compute resources, and safety thresholds still apply.

## 5. Users and Personas

| Persona | Need | Success Criteria |

| --- | --- | --- |

| Self-directed learner | Turn a broad question or collection of files into a full course. | Receives a coherent syllabus, lectures, assignments, and study path that teach from fundamentals to advanced concepts. |

| Course author / educator | Create or customize a complete course package for teaching. | Can review the plan, edit constraints, regenerate sections, and export materials. |

| Developer / builder | Use the CLI as a content-generation backend for future products. | Receives stable JSON/Markdown outputs, deterministic IDs, logs, and schemas for downstream integration. |

| Future VR learner | Experience the generated course as a simulated university. | VR app can import lecture scripts, professor cues, labs, assignments, and interaction anchors without reprocessing the raw course. |



## 6. Assumptions

- The initial prompt is education-related and asks to learn or understand a concept, field, paper set, codebase, or knowledge domain deeply.

- Default course length is 24 weeks, approximating nearly six months. This must be configurable because some university semesters are shorter.

- Default lecture cadence is two lectures per week, each targeting approximately two hours of spoken instruction.

- Default lab cadence is one lab per week when the subject benefits from labs. Lab generation must support auto, always, and never modes.

- The CLI should support a directory as the main context input and should handle very large source sets through indexing, chunking, summarization, and staged retrieval rather than attempting to pass all files into a single model call.

- The first release is local-first: course artifacts are written to a local output directory.

- The VR application is not built in the CLI phase, but the CLI must produce future-ready metadata for scenes, lecture timing, lab activities, professor cues, and interaction anchors.

## 7. Primary User Journeys

### 7.1 Prompt-Only Course Generation

1. User runs aiu course create with a prompt and default settings.

2. CLI analyzes the prompt, infers scope, prerequisites, target level, course length, and lab usefulness.

3. CLI generates a course blueprint and asks for approval before generating the full course package.

4. User approves or edits the plan.

5. CLI generates syllabus, lectures, labs, assignments, assessments, rubrics, and export metadata in stages.

6. CLI validates the package and writes a final report.

### 7.2 Course Generation from Files or Directory

1. User points the CLI at a directory, zip, repository, PDF set, images, or mixed file collection.

2. CLI inventories files, extracts text/metadata, indexes content, and creates a source manifest.

3. CLI identifies core topics, prerequisites, source coverage, contradictions, and missing knowledge.

4. CLI produces a course plan grounded in the provided materials and optional external research.

5. CLI generates artifacts with source citations back to the user material and research references.

### 7.3 Resume or Regenerate Part of a Course

1. User runs aiu course status to inspect what has been generated.

2. User runs aiu course generate --from week:08 --to week:10 or aiu course regenerate lectures/week_08_day_01.md.

3. CLI reuses the manifest, dependency graph, source index, and locked course plan to regenerate the selected pieces.

4. CLI updates validation reports and preserves prior outputs unless explicitly overwritten.

## 8. Functional Requirements

Priority labels: P0 = required for CLI MVP, P1 = required soon after MVP, P2 = future enhancement.

| ID | Priority | Area | Requirement | Acceptance Criteria |

| --- | --- | --- | --- | --- |

| FR-001 | P0 | Project initialization | CLI shall create an AI University project directory with config, output folders, logs, and a course manifest. | Running aiu init or aiu course create creates a valid project with course.yaml, manifest.json, logs/, and artifacts/. |

| FR-002 | P0 | Provider configuration | CLI shall support provider setup via Codex subscription path, API key path, and a provider adapter abstraction. | User can configure provider credentials without embedding secrets in course outputs. |

| FR-003 | P0 | Prompt intake | CLI shall accept a raw learning prompt from command argument, stdin, or a prompt file. | Prompt is stored in prompt.md and referenced in the manifest. |

| FR-004 | P0 | Context intake | CLI shall accept files, images, archives, and local directories as context inputs. | The source manifest lists every ingested input with path, type, size, checksum, extraction status, and errors. |

| FR-005 | P0 | Large source handling | CLI shall process large directories through inventory, extraction, chunking, indexing, and retrieval instead of one-shot context stuffing. | A large directory can be indexed and used for generation with progress reporting and resumable state. |

| FR-006 | P0 | Learning-intent analysis | Engine shall analyze the prompt to identify subject area, target learner level, prerequisites, desired depth, practical vs theoretical balance, and lab usefulness. | Course blueprint contains an intent_analysis section with inferred assumptions and editable parameters. |

| FR-007 | P0 | Course blueprint | Engine shall generate a long-form course plan before full artifact generation. | Blueprint includes title, description, prerequisites, learning outcomes, weekly schedule, modules, lecture topics, labs, assignments, assessments, and expected deliverables. |

| FR-008 | P0 | Approval gate | CLI shall support an approval or --yes mode before expensive full generation. | Default interactive mode pauses after blueprint generation; non-interactive mode can proceed when --yes is passed. |

| FR-009 | P0 | Lecture transcript generation | Engine shall generate two lecture transcripts per week by default, each targeting a two-hour lecture unless configured otherwise. | For a 24-week default course, the schedule includes 48 lecture transcript artifacts with stable IDs. |

| FR-010 | P0 | Lab generation | Engine shall generate weekly lab transcripts and lab instructions when the course benefits from hands-on work. | Lab policy can be auto, always, or never; auto mode explains why labs are or are not included. |

| FR-011 | P0 | Homework and activities | Engine shall generate homework, readings, practice exercises, in-class activities, discussion prompts, and optional projects. | Each week has appropriate learner work tied to lecture objectives. |

| FR-012 | P0 | Quizzes and tests | Engine shall generate quizzes, midterm/final exams or equivalent tests, answer keys, rubrics, and study guides. | Assessment artifacts map to learning objectives and include grading guidance. |

| FR-013 | P0 | Source grounding | Engine shall cite provided source files and external research sources where used. | Generated artifacts include provenance metadata or inline references sufficient to trace claims to source material. |

| FR-014 | P0 | Validation | Engine shall validate completeness, schedule consistency, source coverage, missing artifacts, broken references, and assessment alignment. | aiu course validate returns pass/warn/fail with actionable issues. |

| FR-015 | P0 | Resumability | Engine shall write checkpoints after each stage and artifact. | Interrupted generation can resume without restarting from the beginning. |

| FR-016 | P0 | Structured output | Engine shall write Markdown for human review and JSON/YAML for machine consumption. | Each artifact has a Markdown body and a JSON metadata sidecar or consolidated index. |

| FR-017 | P0 | VR handoff metadata | Engine shall emit future-ready scene and timing metadata for lectures, labs, assignments, and interaction anchors. | Generated package includes vr_handoff/ with stable schemas even though VR rendering is out of scope. |

| FR-018 | P1 | Selective regeneration | CLI shall regenerate individual weeks, lectures, labs, or assessments without rebuilding the entire course. | User can target a subset by artifact ID or range. |

| FR-019 | P1 | Export formats | CLI shall support exports such as markdown bundle, JSON package, static HTML, and LMS-ready structures. | aiu course export creates selected target formats and a validation summary. |

| FR-020 | P1 | Cost and usage reporting | CLI shall estimate and report model usage, elapsed time, tokens/credits where provider data is available, and failed retries. | Generation report includes usage_summary with provider-specific fields. |

| FR-021 | P1 | MCP server management | CLI shall list, enable, disable, and configure MCP servers used by the engine. | User can inspect which tools/resources/prompts are exposed before generation. |

| FR-022 | P1 | Human-in-the-loop tool safety | CLI shall require confirmation for risky MCP tool calls such as network access, code execution, file writes outside the project, or shell commands. | Risky actions are denied unless approved or explicitly allowed by config. |

| FR-023 | P2 | Interactive Q&A preparation | Engine shall generate anticipated student questions and professor responses for future real-time lecture interactions. | VR handoff metadata includes interaction_anchors and likely_questions per lecture segment. |

| FR-024 | P2 | Adaptive course variants | Engine shall generate alternate course variants for beginner, intermediate, advanced, professional, or child-friendly levels. | User can request variants without re-ingesting sources. |



## 9. Proposed CLI Interface

The exact command names may change, but the product should preserve these capabilities.

```
# Configure AI University
aiu init
aiu auth login --provider codex
aiu auth login --provider openai --api-key-env OPENAI_API_KEY

# Create a course from a prompt only
aiu course create "Teach me machine learning from first principles" \
  --weeks 24 \
  --lectures-per-week 2 \
  --lecture-hours 2 \
  --lab-policy auto \
  --level beginner \
  --output ./courses/machine-learning

# Create a course from a prompt plus a directory of materials
aiu course create --prompt ./prompt.md \
  --context ./materials \
  --context ./notes.zip \
  --context ./diagrams \
  --provider codex \
  --output ./courses/custom-course

# Review, approve, generate, validate, and export
aiu course plan ./courses/custom-course
aiu course approve ./courses/custom-course
aiu course generate ./courses/custom-course
aiu course status ./courses/custom-course
aiu course validate ./courses/custom-course
aiu course export ./courses/custom-course --format markdown,json,vr

# Regenerate a subset
aiu course regenerate ./courses/custom-course --artifact lecture:w08:d01
aiu course generate ./courses/custom-course --from week:10 --to week:12
```

## 10. Core Generation Pipeline

| Stage | Purpose | Key Outputs |

| --- | --- | --- |

| 1. Initialize project | Create local workspace, config, and manifest. | course.yaml, prompt.md, logs/, artifacts/ |

| 2. Ingest sources | Inventory and extract files/directories/images/archives. | source_manifest.json, extracted_text/, image_descriptions/, ingest_report.json |

| 3. Index context | Chunk, embed or otherwise index sources for retrieval and citation. | source_index/, chunk_manifest.json |

| 4. Analyze learning intent | Infer target level, prerequisites, scope, and learning outcomes. | intent_analysis.json |

| 5. Plan curriculum | Design a semester-length course structure. | course_blueprint.md/json, schedule.json |

| 6. Optional approval | Let user review/edit plan before large generation. | approved_course_blueprint.json |

| 7. Generate artifacts | Generate lectures, labs, homework, quizzes, exams, rubrics, projects, and study aids. | lectures/, labs/, homework/, quizzes/, exams/, rubrics/ |

| 8. Validate | Check completeness, consistency, grounding, and downstream readiness. | validation_report.json, warnings.md |

| 9. Package/export | Create human and machine-readable bundles. | exports/, vr_handoff/, course_package.json |



The engine should maintain a dependency graph so, for example, a final exam can reference course-wide learning objectives and generated lectures, while individual lectures are generated from the approved schedule and source-retrieval plan. This avoids drift and supports targeted regeneration.

## 11. System Architecture

Recommended architecture:

```
CLI Shell
  -> Project Manager
  -> Auth / Provider Manager
  -> MCP Client Manager
  -> Ingestion Engine
       -> File Inventory
       -> Extractors: text, PDF, image, archive, code, data
       -> Chunker and Source Index
  -> Course Orchestrator
       -> Intent Analyzer
       -> Curriculum Planner
       -> Lecture Generator
       -> Lab Generator
       -> Assignment and Assessment Generator
       -> Rubric and Answer-Key Generator
       -> VR Handoff Generator
  -> Validation Engine
  -> Artifact Store
  -> Exporter
  -> Logs, Usage, and Checkpoints
```

| Component | Responsibilities |

| --- | --- |

| CLI Shell | Parse commands, render progress, handle interactive approvals, and provide exit codes for automation. |

| Project Manager | Create and manage course directories, config files, manifests, and artifact IDs. |

| Provider Manager | Abstract model providers, authentication modes, request retries, rate limits, and usage accounting. |

| MCP Client Manager | Connect to approved MCP servers for tools, resources, prompts, and sampling-compatible workflows. |

| Ingestion Engine | Process user files/directories, extract text and metadata, describe images, and build searchable source indexes. |

| Course Orchestrator | Execute the pipeline, maintain dependency graph, schedule jobs, and resume interrupted generation. |

| Generation Modules | Produce syllabus, lectures, labs, homework, quizzes, exams, rubrics, projects, study guides, and VR metadata. |

| Validation Engine | Check artifact completeness, consistency, citation coverage, pedagogy alignment, and machine-readable schema validity. |

| Artifact Store | Write Markdown, JSON, YAML, logs, source references, generated IDs, and checksums. |

| Exporter | Package course outputs for human reading, downstream applications, and future VR import. |



## 12. Output Package Specification

Default output directory structure:

```
course-root/
  course.yaml
  manifest.json
  prompt.md
  course_blueprint.md
  course_blueprint.json
  rails.json
  schedule.json
  source_manifest.json
  ingest_report.json
  validation_report.json
  logs/
  source_index/
  extracted_sources/
  syllabus/
    syllabus.md
    grading_policy.md
    reading_list.md
  lectures/
    week_01/day_01.md
    week_01/day_01.json
    week_01/day_02.md
    week_01/day_02.json
  labs/
    week_01_lab.md
    week_01_lab.json
  homework/
  quizzes/
  exams/
  projects/
  rubrics/
  answer_keys/
  study_guides/
  vr_handoff/
    course_runtime_manifest.json
    lecture_scene_cues/
    lab_scene_cues/
    interaction_anchors/
  exports/
```

### 12.1 Core Data Objects

| Object | Description | Required Fields |

| --- | --- | --- |

| CourseManifest | Top-level metadata for the generated course package. | course_id, title, version, prompt_ref, settings, created_at, provider, artifact_index |

| SourceManifest | Inventory of user-provided and researched sources. | source_id, path_or_url, type, checksum, extraction_status, chunks, citation_label |

| CourseBlueprint | Approved course plan and dependency anchor. | course_title, outcomes, prerequisites, modules, week_plan, assessment_plan, lab_policy |

| LectureSession | One lecture transcript and metadata. | lecture_id, week, day, title, objectives, transcript, source_refs, estimated_duration, vr_cues |

| LabSession | Lab transcript/instructions when applicable. | lab_id, week, goals, setup, steps, expected_outputs, safety_notes, rubric |

| Assessment | Quiz, homework, project, midterm, final, or activity. | assessment_id, type, objectives, prompt, questions, answer_key, rubric, due_week |

| VRHandoffCue | Future graphics/VR metadata. | cue_id, artifact_id, timestamp_or_segment, scene_type, professor_action, visual_aid, interaction_anchor |

| ValidationReport | Quality and completeness report. | status, checks, warnings, failures, artifact_counts, citation_coverage, schema_errors |



## 13. Course Content Requirements

### 13.1 Course Blueprint

- Course title, short description, target learner, prerequisites, and assumed background.

- Learning outcomes that move from fundamentals to advanced application.

- Weekly schedule for the configured course duration.

- Module breakdown with dependencies and rationale for ordering.

- Lecture objectives for every lecture.

- Lab policy and lab plan where relevant.

- Assessment strategy: homework, quizzes, projects, exams, and grading rubric.

- Source usage plan showing which files or research sources support which course modules.

### 13.2 Lecture Transcripts

- Each lecture must read like what a professor would say in a two-hour university lecture, not just an outline.

- Each lecture must include opening context, conceptual explanations, examples, analogies, transitions, recap points, checks for understanding, and closing summary.

- Lectures must build on prior lectures and preview upcoming work.

- Where useful for VR, transcripts should include cues such as pauses, board work, slide references, demonstration moments, and likely student questions.

- Every lecture must map to learning objectives and source references.

### 13.3 Labs

- Labs should be generated when the subject benefits from hands-on application, simulation, problem solving, experiments, code, design, analysis, or practice.

- Each lab must include setup, instructor/lab-assistant transcript, steps, expected outcomes, troubleshooting, deliverables, and rubric.

- For non-lab-friendly topics, the engine should generate alternate recitation, seminar, case-study, or workshop activities instead of forcing fake labs.

### 13.4 Homework, Quizzes, Tests, Projects, and Activities

- Weekly homework should reinforce lecture objectives and include problem sets, essays, design tasks, coding tasks, readings, or applied exercises as appropriate.

- Quizzes should be short, frequent checks for understanding.

- Tests should include midterm and final or equivalent cumulative assessments.

- Projects should synthesize multiple weeks of learning when appropriate.

- Rubrics and answer keys must be generated for all graded artifacts.

- Study guides and review sessions should be included before major exams.

## 14. Pedagogical Requirements

- Teach from fundamentals. The course must not assume the user already understands the core concept unless the user sets an advanced level.

- Use scaffolding. Introduce prerequisites before dependent concepts.

- Use varied practice. Mix explanation, demonstration, guided practice, independent work, reflection, and assessment.

- Use spaced reinforcement. Revisit difficult concepts across lectures, assignments, labs, and quizzes.

- Use measurable outcomes. Each week and assessment should map back to explicit learning objectives.

- Use source-grounded instruction when user files are supplied. The course should make it clear when content comes from the user corpus versus general research.

- Prefer honesty over false certainty. If source materials are incomplete, contradictory, or insufficient for a course topic, the engine should flag gaps rather than inventing facts.

## 15. Future VR/Graphics Handoff Requirements

The CLI must not implement the VR application, but it should produce structured metadata so the future graphics layer can render and orchestrate the course experience without reinterpreting all raw text.

| VR Need | CLI/Core Engine Output |

| --- | --- |

| Professor lectures | Lecture transcript broken into segments with timestamps or estimated timing, emphasis, board/slide cues, and interaction anchors. |

| Classroom environment | Scene type, lecture title, module context, visual aid references, and suggested environment metadata. |

| Real-time questions | Likely student questions, expected professor answers, and safe retrieval anchors for context-aware Q&A. |

| Labs | Lab room type, materials, setup, procedural steps, success criteria, and lab-assistant narration. |

| Assignments and tests | Due dates, instructions, grading rubrics, feedback templates, and generated answer keys. |

| Course progression | Week/day schedule, prerequisites, completion state hooks, and artifact dependency graph. |



The VR handoff schema should be considered part of the CLI MVP because retrofitting structured cues after generating massive transcripts would be expensive and error-prone.

## 16. Non-Functional Requirements

| Category | Requirement |

| --- | --- |

| Reliability | Generation must be checkpointed and resumable. Failed artifacts should not corrupt completed artifacts. |

| Performance | The engine should support long-running jobs with progress updates, streaming logs, and parallel generation where safe. |

| Scalability | No arbitrary product-level zip or directory limit; practical limits should be governed by local disk, configured safety thresholds, and provider limits. |

| Portability | Outputs should be plain files: Markdown, JSON, YAML, and asset folders. Avoid proprietary storage formats for core artifacts. |

| Extensibility | Provider adapters, MCP servers, extractors, validators, and exporters should be pluggable. |

| Security | Local files should only be read from user-approved paths. Risky MCP tool calls require clear user approval. |

| Privacy | Secrets must not be written to course artifacts. Local source paths can be redacted in export mode. |

| Observability | Logs should include stage status, artifact IDs, retries, provider usage where available, validation results, and warnings. |

| Determinism | Artifact IDs, folder paths, and schema keys should remain stable across runs unless content is intentionally regenerated. |

| Cross-platform | CLI should target macOS, Windows, and Linux, with clear handling of path separators and shell differences. |



## 17. Security and Privacy Requirements

- Credentials must be read from secure provider login, OS credential store, environment variable, or explicit config reference. They must never be embedded in generated course files.

- The CLI must maintain a project allowlist of readable directories and files.

- The CLI must display which MCP servers are enabled and what categories of tools/resources/prompts they expose.

- Network access, shell execution, external file writes, and destructive operations must require explicit approval or a clearly documented non-interactive allow policy.

- Source manifests should store checksums and relative paths by default. Absolute path export should be optional.

- Generated materials should include warnings when the user corpus may contain copyrighted, sensitive, proprietary, or personally identifiable data.

- The engine should support ignore patterns such as .gitignore, aiuignore, and explicit exclude globs.

## 18. Error Handling Requirements

| Scenario | Expected Behavior |

| --- | --- |

| Provider authentication fails | Show provider-specific remediation steps and do not begin generation. |

| Provider rate limit or usage limit reached | Checkpoint current state, report what completed, and allow resume or model/provider switch. |

| Unsupported file type | Record as skipped in ingest_report.json with reason; continue where possible. |

| Corrupt archive or unreadable file | Report source-level error and continue ingesting other sources. |

| Insufficient context for requested depth | Generate a warning and propose research augmentation or narrower scope. |

| Validation fails | Return non-zero exit code in automation mode and write actionable validation failures. |

| User cancels generation | Finish current safe write, checkpoint, and exit with resumable state. |



## 19. MVP Definition

The CLI MVP is complete when a user can run one command with a learning prompt and optional directory, approve a generated plan, and receive a validated full course package for the configured duration. The package must contain syllabus, course plan, lectures, labs or lab alternatives, homework, quizzes, tests, rubrics, answer keys, study guides, source manifests, validation report, and VR handoff metadata.

### 19.1 MVP Must Include

- Interactive and non-interactive CLI modes.

- Provider setup for at least one Codex/OpenAI-compatible path plus adapter interface for future providers.

- Prompt intake from argument, stdin, or file.

- Context intake from local files, directories, archives, and images.

- Ingestion report and source manifest.

- Course blueprint generation with approval gate.

- Full artifact generation for a default 24-week course or user-configured length.

- Lecture, lab, assignment, assessment, rubric, answer-key, and study-guide generators.

- Validation and resumability.

- Markdown plus JSON/YAML outputs.

- Initial VR handoff schema.

### 19.2 Post-MVP Enhancements

- Static HTML or web preview.

- LMS export packages.

- Advanced analytics for prerequisite gaps and mastery mapping.

- Interactive learner progress tracking.

- Live Q&A runtime integration.

- Voice synthesis, avatar timing, visual slide generation, and full VR scene orchestration.

## 20. Success Metrics

| Metric | Target Direction | Why It Matters |

| --- | --- | --- |

| Course completion rate | Increase | Measures whether full course generation completes without manual recovery. |

| Validation pass rate | Increase | Measures package completeness and structural quality. |

| Plan approval rate | Increase | Measures whether the first blueprint matches user intent. |

| Regeneration success rate | Increase | Measures resumability and targeted rebuild quality. |

| Citation/source coverage | Increase | Measures grounding in user files and research. |

| Cost per completed course | Decrease or predictable | A full semester is large, so cost transparency is essential. |

| VR import readiness | Increase | Measures whether generated metadata can be consumed downstream. |

| User edits required per course | Decrease | Measures practical usability of generated materials. |



## 21. Acceptance Criteria

- Given a prompt-only request, the CLI creates a course project, generates a blueprint, obtains approval or honors --yes, generates all required artifacts, validates the package, and exits successfully.

- Given a directory of source files, the CLI inventories the directory, extracts/indexes readable content, cites sources in generated materials, and records skipped/unreadable files.

- Given an interruption, the CLI can resume from the last completed stage without overwriting completed artifacts unexpectedly.

- Given a default 24-week configuration, the generated schedule includes 48 lectures and an appropriate lab/recitation/workshop cadence.

- Given lab-policy always, every week includes a lab artifact. Given lab-policy never, no labs are generated and alternate activities are used where appropriate.

- Given validation, the report identifies missing artifacts, broken references, schema issues, and assessment/objective misalignment.

- Given export --format vr, the output includes course_runtime_manifest.json and structured cue files for lecture and lab scenes.

## 22. Open Product Questions

- Should the default course duration be fixed at 24 weeks or should the CLI ask for confirmation when the prompt appears narrower than a full semester?

- What exact transcript length should represent a two-hour lecture: word-count target, segment-count target, or provider-specific generation budget?

- Should the engine generate lecture slides in the CLI phase, or only slide/visual cues for later graphics generation?

- Should external research be enabled by default, opt-in, or required only when user-provided sources are insufficient?

- Which provider paths are mandatory for the first build: Codex subscription, OpenAI API key, both, or a generic provider interface first?

- What should the first VR handoff schema optimize for: Unity, Unreal, WebXR, or engine-agnostic JSON?

## 23. References

[1] Model Context Protocol docs. MCP is an open-source standard for connecting AI applications to external systems, including data sources, tools, and workflows. URL: https://modelcontextprotocol.io/docs/getting-started/intro

[2] MCP tools specification. MCP servers can expose tools that models can discover and invoke, with human-in-the-loop safety guidance. URL: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

[3] MCP resources specification. MCP servers can expose resources such as files, schemas, or app-specific information as context. URL: https://modelcontextprotocol.io/specification/2025-06-18/server/resources

[4] MCP prompts specification. MCP servers can expose prompt templates that clients can discover and execute with arguments. URL: https://modelcontextprotocol.io/specification/2025-06-18/server/prompts

[5] OpenAI Codex CLI docs. Codex CLI runs locally in a terminal and can inspect selected directories; docs state ChatGPT Plus, Pro, Business, Edu, and Enterprise plans include Codex. URL: https://developers.openai.com/codex/cli

[6] OpenAI Codex authentication docs. Codex supports ChatGPT sign-in for subscription access and API key sign-in for usage-based access. URL: https://developers.openai.com/codex/auth
