# AI University CLI

AI University is a local-first CLI and core engine for turning a learning prompt
and optional source materials into a structured university-style course package.

This repository currently contains the initial Python package scaffold.

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

```bash
aiu --help
aiu --version
aiu init --help
aiu auth --help
aiu course --help
```

The operational course-generation commands are scaffolded first and will be
implemented incrementally by the task plan.

## Tests

```bash
pytest
```
