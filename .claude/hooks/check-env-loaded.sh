#!/usr/bin/env bash
# SessionStart hook: warn if env vars from .claude/settings.local.json
# weren't loaded into the shell before Claude Code started.
#
# Why: MCP servers inherit env from the Claude Code parent process. Settings
# in .claude/settings.local.json are NOT auto-injected into MCP server
# subprocesses, so tokens must be exported in the shell first via
# scripts/load-local-env.sh. This hook is the canary if that step was missed.

set -euo pipefail

settings_file="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/settings.local.json"
[[ -f "$settings_file" ]] || exit 0

missing=()
while IFS= read -r key; do
  # Indirect expansion: get the current value of the variable named "$key".
  current="${!key-}"
  if [[ -z "$current" || "$current" == "\${$key}" ]]; then
    missing+=("$key")
  fi
done < <(jq -r '.env // {} | keys[]' "$settings_file")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "[env check] These vars from settings.local.json are NOT in Claude Code's env:" >&2
  for k in "${missing[@]}"; do
    echo "  - $k" >&2
  done
  echo "[env check] Fix: in your shell, run \`eval \"\$($CLAUDE_PROJECT_DIR/scripts/load-local-env.sh)\"\` then restart Claude Code." >&2
fi
