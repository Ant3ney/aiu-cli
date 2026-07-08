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
aiu course status ./courses/compilers
```

`aiu init` refuses to initialize an existing non-empty directory unless
`--force` is supplied. With `--force`, it recreates the required AI University
directory layout and overwrites `course.yaml` and `manifest.json`; unrelated
files are left in place.

`aiu course create ... --yes` initializes the project, stores the prompt,
ingests/extracts local context, plans, approves, generates
syllabus/lectures/labs/assessments, validates, and writes logs to `logs/aiu.log`.

## Troubleshooting

- Validation failures write `validation_report.json` and `warnings.md`.
- `aiu course status <course>` reads `.aiu/state.json` to show completed,
  pending, failed, and skipped stages.
- Re-run `aiu course generate <course>` to resume completed stages without
  rewriting them, or use `--force` for an intentional regeneration.
- Use `aiu course regenerate <course> --artifact lecture:w08:d01` for targeted
  lecture regeneration.

## Tests

```bash
ruff check .
pytest
```
