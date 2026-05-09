#!/usr/bin/env bash
# Emit `export K=V` lines for every key under `.env` in .claude/settings.local.json.
# Intended to be eval'd: `eval "$(./scripts/load-local-env.sh)"`.
#
# Single source of truth for project-local env vars (tokens, paths). Settings
# file stays gitignored; this script just bridges it into the shell so that
# Claude Code (and the MCP servers it forks) inherit the values.

set -euo pipefail

settings_file="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/settings.local.json"

if [[ ! -f "$settings_file" ]]; then
  echo "load-local-env: $settings_file not found" >&2
  exit 1
fi

# `@sh` quotes values safely for shell consumption.
jq -r '.env // {} | to_entries[] | "export \(.key)=\(.value | @sh)"' "$settings_file"
