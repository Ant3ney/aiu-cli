#!/usr/bin/env bash
set -euo pipefail

# Edit these values for each course preview.
# Relative paths are resolved from the directory where you run this script.

PROMPT_TEXT="Create a university-style course from these source materials."

# Set PROMPT_FILE to use a Markdown/text prompt file instead of PROMPT_TEXT.
# Example: PROMPT_FILE="./course_prompt.md"
PROMPT_FILE=""

# Add one or more files, directories, or zip archives to use as course source material.
CONTEXT_PATHS=(
  "./materials"
  # "./notes.md"
  # "./references.zip"
)

OUTPUT_DIR="./courses/my-course-preview"
PROVIDER="codex"
LEVEL="beginner"
WEEKS="24"
LECTURES_PER_WEEK="2"
LECTURE_HOURS="2.0"
LAB_POLICY="auto"
GENERATE_UNTIL="syllabus"

EXCLUDE_PATTERNS=(
  "*.mp4"
  "*.mov"
  # "node_modules/"
)

AIU_BIN="${AIU_BIN:-aiu}"
CALL_DIR="${PWD}"

from_call_dir() {
  local path="$1"

  if [[ -z "$path" ]]; then
    printf '%s\n' "$path"
  elif [[ "$path" == "~" ]]; then
    printf '%s\n' "$HOME"
  elif [[ "$path" == "~/"* ]]; then
    printf '%s/%s\n' "$HOME" "${path#~/}"
  elif [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s/%s\n' "$CALL_DIR" "$path"
  fi
}

args=(
  course create
  --output "$(from_call_dir "$OUTPUT_DIR")"
  --provider "$PROVIDER"
  --level "$LEVEL"
  --weeks "$WEEKS"
  --lectures-per-week "$LECTURES_PER_WEEK"
  --lecture-hours "$LECTURE_HOURS"
  --lab-policy "$LAB_POLICY"
  --generate-until "$GENERATE_UNTIL"
)

if [[ -n "$PROMPT_FILE" ]]; then
  prompt_path="$(from_call_dir "$PROMPT_FILE")"
  if [[ ! -f "$prompt_path" ]]; then
    printf 'Prompt file does not exist: %s\nResolved to: %s\n' "$PROMPT_FILE" "$prompt_path" >&2
    exit 1
  fi
  args+=(--prompt "$prompt_path")
else
  args+=("$PROMPT_TEXT")
fi

for context_path in "${CONTEXT_PATHS[@]}"; do
  [[ -z "$context_path" ]] && continue
  resolved_context_path="$(from_call_dir "$context_path")"
  if [[ ! -e "$resolved_context_path" ]]; then
    printf 'Context path does not exist: %s\nResolved to: %s\n' \
      "$context_path" "$resolved_context_path" >&2
    exit 1
  fi
  args+=(--context "$resolved_context_path")
done

for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  [[ -z "$pattern" ]] && continue
  args+=(--exclude "$pattern")
done

printf 'Running AIU from: %s\n' "$CALL_DIR"
exec "$AIU_BIN" "${args[@]}"
