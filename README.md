# AI University CLI

AI University is a CLI and core engine for turning a learning prompt and
optional source materials into a structured university-style course package.

The CLI supports three provider modes:

- `codex`: uses your local Codex CLI login. No OpenAI API key is required.
- `openai`: uses an OpenAI-compatible API key from an environment variable. No
  Codex install or login is required.
- `fake`: deterministic offline provider for tests and demos.

## Global install

Install prerequisites on Ubuntu:

```bash
sudo apt update
sudo apt install git python3-pipx
```

Install prerequisites on Arch Linux:

```bash
sudo pacman -S git python-pipx
```

```bash
cd /path/to/ai_university_cli
python -m pip install --user pipx
python -m pipx ensurepath
pipx install .
aiu --version
```

For an editable development install instead:

```bash
cd /path/to/ai_university_cli
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Update

Run this from any directory:

```bash
aiu update
```

`aiu update` finds the AIU source checkout, pulls the latest GitHub source code
there, and reinstalls AIU with the Python environment that is running the CLI.
It does not run `git pull` in the directory where you typed the command.

If AIU was installed without a local git checkout, the updater creates or reuses
a managed clone at `~/.local/share/aiu-cli/source` unless `XDG_DATA_HOME` is set.
You can preview the exact commands first:

```bash
aiu update --dry-run
```

Use an explicit checkout when needed:

```bash
aiu update --source-dir /path/to/ai_university_cli
```

## Authentication

Choose one provider path. Codex and API-key auth are independent.

### Option A: Codex login

Install and authenticate Codex first:

```bash
codex --version
codex login
codex login status
```

If browser login is awkward on your machine, use device auth:

```bash
codex login --device-auth
codex login status
```

Then register Codex with AI University:

```bash
aiu auth login --provider codex
aiu auth status
```

This stores only the fact that AIU should use the local `codex` command. AIU
does not read or copy Codex tokens from `~/.codex/auth.json`.

When `--provider codex` is used, AIU invokes Codex in yolo mode with
`--dangerously-bypass-approvals-and-sandbox`. Use this only in course
workspaces you trust.

### Option B: OpenAI-compatible API key

Use this path when you want API-key billing instead of Codex login:

```bash
export OPENAI_API_KEY="your_api_key"
aiu auth login --provider openai --api-key-env OPENAI_API_KEY
aiu auth status
```

This stores the environment variable name, not the key value. Codex is not
required for this mode.

### Option C: Fake provider

Use this for local smoke tests without network or credentials:

```bash
aiu auth login --provider fake
```

## Generate a course

With Codex:

```bash
aiu course create "Teach me artificial intelligence" \
  --provider codex \
  --output ./courses/ai \
  --yes
```

With an API key:

```bash
export OPENAI_API_KEY="your_api_key"
aiu course create "Teach me artificial intelligence" \
  --provider openai \
  --output ./courses/ai-api \
  --yes
```

With the deterministic fake provider:

```bash
aiu course create "Teach me artificial intelligence" \
  --provider fake \
  --output ./courses/ai-fake \
  --yes
```

## Preview and refine the syllabus before generating the full course

Use `--generate-until syllabus` when you want to inspect the course plan before
AIU spends time generating every lecture, lab, and assessment. The path passed to
`--output` is your course folder; use that same folder in the later feedback,
generate, resume, validate, and export commands.

1. Create the project and stop after the syllabus preview:

```bash
aiu course create "Teach me data-driven creature collector RPG design" \
  --provider fake \
  --output ./courses/rpg \
  --generate-until syllabus
```

2. Review the generated preview files:

```bash
less ./courses/rpg/syllabus/syllabus.md
less ./courses/rpg/course_blueprint.md
less ./courses/rpg/context_research.md
```

When local context is supplied, AIU now runs a source research pass before the
blueprint or syllabus preview. It scans the extracted chunks, writes
`context_research.md` and `source_index/context_research.json`, and uses those
notes to ground the course plan, reading list, and later lecture prompts. With a
real provider such as `codex` or `openai`, AIU also asks the provider to study
compact source packets module by module and synthesize citation guidance for
future course generation.

3. If the plan is missing topics, add feedback. You can run this command more
than once; each note is appended to `course_feedback.md`, then AIU regenerates
the blueprint and syllabus preview from all accumulated feedback.

```bash
aiu course feedback ./courses/rpg \
  "Make sure the course covers creature stat schemas, evolution rules, battle balance, and content authoring tools."
```

4. Review the regenerated syllabus. If it still needs changes, repeat
`aiu course feedback <course-folder> "...your feedback..."`.

5. When the syllabus looks right, start full course generation:

```bash
aiu course generate ./courses/rpg
```

`--generate-until syllabus` creates an approved blueprint snapshot so the next
`aiu course generate <course-folder>` command can begin immediately. If you want
an explicit approval command after review, run:

```bash
aiu course approve ./courses/rpg
aiu course generate ./courses/rpg
```

If full generation is interrupted later, continue from checkpointed artifacts:

```bash
aiu course resume ./courses/rpg --yes
```

Replace `./courses/rpg` with the actual folder you supplied to `--output`; it is
not a required name.

Then validate and export:

```bash
aiu course validate ./courses/ai
aiu course export ./courses/ai --format markdown,json,vr
```

For staged work:

```bash
aiu course create "Teach me compilers" --output ./courses/compilers --init-only
aiu course plan ./courses/compilers
aiu course approve ./courses/compilers
aiu course generate ./courses/compilers --stage lectures
aiu course resume ./courses/compilers --yes
aiu course status ./courses/compilers
```

`aiu init` refuses to initialize an existing non-empty directory unless
`--force` is supplied. With `--force`, it recreates the required AI University
directory layout and overwrites `course.yaml` and `manifest.json`; unrelated
files are left in place.

`aiu course create ... --yes` initializes the project, stores the prompt,
ingests/extracts local context, plans, approves, generates
syllabus/lectures/labs/assessments, validates, and writes logs to `logs/aiu.log`.
Long-running create/generate commands also stream a loading view with stage
progress, artifact paths, compact previews of newly generated course content,
and periodic notes while the course package is being assembled.

By default, each generated lecture targets two hours of professor speech. AIU
enforces this as a minimum transcript length of 18,000 words per lecture
(`2.0 hours * 60 minutes * 150 spoken words/minute`). The `--lecture-hours`
option is available for explicit custom runs, and validation scales the required
word count from that configured duration.

## Troubleshooting

- Validation failures write `validation_report.json` and `warnings.md`.
- `aiu course status <course>` reads `.aiu/state.json` to show completed,
  pending, failed, and skipped stages.
- If course creation was interrupted, run `aiu course resume <course> --yes`
  to continue from checkpointed artifacts and finish validation.
- If an existing blueprint needs to be rebuilt after planner improvements, run
  `aiu course plan <course> --force`, then approve and generate again.
- Re-run `aiu course generate <course>` to resume completed stages without
  rewriting them, or use `--force` for an intentional regeneration.
- Use `aiu course regenerate <course> --artifact lecture:w08:d01` for targeted
  lecture regeneration.

## Tests

```bash
ruff check .
pytest
```
