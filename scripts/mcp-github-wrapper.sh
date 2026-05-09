#!/usr/bin/env bash
# Wrapper that boots the GitHub MCP server with GITHUB_PERSONAL_ACCESS_TOKEN
# read from .claude/settings.local.json.
#
# Why this exists: Claude Code does NOT expand ${VAR} references in .mcp.json
# `env` blocks against settings.local.json, and GUI-launched Claude Code does
# not read shell rc files. So the only reliable place to inject the token is
# inside the MCP server's own startup — i.e. here, right before exec'ing npx.
# The token never enters the parent process env, never enters git, and the
# user only configures it in one place: .claude/settings.local.json.

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
settings_file="$script_dir/../.claude/settings.local.json"

if [[ ! -f "$settings_file" ]]; then
  echo "mcp-github-wrapper: $settings_file not found — copy from .example and fill in token" >&2
  exit 1
fi

token="$(jq -r '.env.GITHUB_PERSONAL_ACCESS_TOKEN // empty' "$settings_file")"
if [[ -z "$token" || "$token" == ghp_xxxxxxxx* ]]; then
  echo "mcp-github-wrapper: GITHUB_PERSONAL_ACCESS_TOKEN missing or placeholder in $settings_file" >&2
  exit 1
fi

export GITHUB_PERSONAL_ACCESS_TOKEN="$token"
exec npx -y @modelcontextprotocol/server-github
