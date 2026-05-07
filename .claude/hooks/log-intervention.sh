#!/bin/bash
# Logs the user's raw prompt to artifacts/<run-id>/interventions.jsonl whenever
# a /test-tickets run is active. A run is "active" iff exactly one
# artifacts/<run-id>/.active marker file exists. The marker is created by the
# /test-tickets skill in Phase 0 and removed in Phase 6.
#
# This hook does NOT decide whether the prompt is a real intervention. /retro
# does that downstream. We just capture everything for later analysis.
#
# Hook event: UserPromptSubmit. Payload arrives on stdin as JSON.
set -euo pipefail

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"
PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // empty')"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty')"
SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty')"

[ -z "$CWD" ] && exit 0
[ -z "$PROMPT" ] && exit 0

# Only fire inside this project.
case "$CWD" in
  */exploratory-test-agent|*/exploratory-test-agent/*) ;;
  *) exit 0 ;;
esac

# Find the unique active run. If zero or >1 markers exist, do nothing — we
# don't know which run to attribute this prompt to and silently appending to
# the wrong run is worse than missing one entry.
shopt -s nullglob
markers=( "$CWD"/artifacts/*/.active )
[ ${#markers[@]} -eq 1 ] || exit 0

run_dir="$(dirname "${markers[0]}")"
log_file="$run_dir/interventions.jsonl"
ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

jq -nc \
  --arg ts "$ts" \
  --arg session "$SESSION" \
  --arg transcript "$TRANSCRIPT" \
  --arg prompt "$PROMPT" \
  '{ts:$ts, kind:"user_prompt", session_id:$session, transcript_path:$transcript, prompt:$prompt}' \
  >> "$log_file"

exit 0
