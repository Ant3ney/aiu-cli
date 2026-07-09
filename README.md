# AI University CLI

AI University is a CLI and core engine for turning a learning prompt and
optional source materials into a structured university-style course package.

The CLI supports three provider modes:

- `codex`: uses your local Codex CLI login. No OpenAI API key is required.
- `openai`: uses an OpenAI-compatible API key from an environment variable. No
  Codex install or login is required.
- `fake`: deterministic offline provider for tests and demos.

## Global install

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

To preview and refine the syllabus before the full course is generated:

```bash
aiu course create "Teach me data-driven creature collector RPG design" \
  --provider fake \
  --output ./courses/rpg \
  --generate-until syllabus

aiu course feedback ./courses/rpg \
  "Make sure the course covers creature stat schemas, evolution rules, battle balance, and content authoring tools."

aiu course generate ./courses/rpg
```

The preview workflow writes `syllabus/syllabus.md` and keeps full lecture, lab,
assessment, and validation generation pending. Feedback is appended to
`course_feedback.md`, then the blueprint and syllabus preview are regenerated
from the accumulated feedback.

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
