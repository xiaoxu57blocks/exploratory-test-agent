#!/usr/bin/env bash
# Install a directory-change shell hook that auto-loads env vars from
# .claude/settings.local.json whenever you cd into a Claude Code project.
#
# Why: Claude Code does NOT inject settings.local.json `env` values into MCP
# server subprocesses. The MCP servers inherit env from the Claude Code parent
# process, so tokens must already be in the shell before `claude` starts.
# This hook makes that automatic.
#
# Idempotent: re-running replaces any previously installed block (matched by
# marker comments) instead of appending duplicates.
#
# Supports zsh and bash. Detects the user's login shell via $SHELL and edits
# the corresponding rc file. Override with --rc <path> if you keep your config
# somewhere unusual.

set -euo pipefail

MARKER_BEGIN="# >>> claude-load-local-env >>>"
MARKER_END="# <<< claude-load-local-env <<<"

usage() {
  cat <<USAGE
Usage: $0 [--rc <path>] [--shell zsh|bash] [--uninstall]

Without flags, detects your shell from \$SHELL and edits ~/.zshrc or ~/.bashrc.
USAGE
}

rc_file=""
shell_kind=""
uninstall=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rc) rc_file="$2"; shift 2 ;;
    --shell) shell_kind="$2"; shift 2 ;;
    --uninstall) uninstall=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$shell_kind" ]]; then
  case "${SHELL:-}" in
    */zsh) shell_kind=zsh ;;
    */bash) shell_kind=bash ;;
    *) echo "Cannot detect shell from \$SHELL=$SHELL. Pass --shell zsh|bash." >&2; exit 2 ;;
  esac
fi

if [[ -z "$rc_file" ]]; then
  case "$shell_kind" in
    zsh) rc_file="$HOME/.zshrc" ;;
    bash) rc_file="$HOME/.bashrc" ;;
    *) echo "Unsupported shell: $shell_kind" >&2; exit 2 ;;
  esac
fi

touch "$rc_file"

# Strip any previously installed block.
tmp="$(mktemp)"
awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
  $0 == b { skip=1; next }
  $0 == e { skip=0; next }
  !skip
' "$rc_file" > "$tmp"
mv "$tmp" "$rc_file"

if [[ $uninstall -eq 1 ]]; then
  echo "Removed claude-load-local-env block from $rc_file"
  exit 0
fi

# Append new block. Heredoc is single-quoted ('BLOCK') so shell does NOT
# expand $PWD, $(...) etc — they go into the rc file literally.
{
  echo ""
  echo "$MARKER_BEGIN"
  if [[ "$shell_kind" == "zsh" ]]; then
    cat <<'BLOCK'
# Auto-load .claude/settings.local.json env vars on cd into a Claude Code project.
_claude_load_local_env() {
  local script="$PWD/scripts/load-local-env.sh"
  if [[ -x "$script" && -f "$PWD/.claude/settings.local.json" ]]; then
    eval "$("$script")"
  fi
}
autoload -U add-zsh-hook
add-zsh-hook chpwd _claude_load_local_env
_claude_load_local_env
BLOCK
  else
    cat <<'BLOCK'
# Auto-load .claude/settings.local.json env vars on cd into a Claude Code project.
_claude_load_local_env() {
  local script="$PWD/scripts/load-local-env.sh"
  if [[ -x "$script" && -f "$PWD/.claude/settings.local.json" ]]; then
    eval "$("$script")"
  fi
}
case ";${PROMPT_COMMAND:-};" in
  *";_claude_load_local_env;"*) ;;
  *) PROMPT_COMMAND="_claude_load_local_env;${PROMPT_COMMAND:-}" ;;
esac
_claude_load_local_env
BLOCK
  fi
  echo "$MARKER_END"
} >> "$rc_file"

echo "Installed claude-load-local-env hook in $rc_file ($shell_kind)."
echo "Activate now: source $rc_file"
echo "Verify:       echo \$GITHUB_PERSONAL_ACCESS_TOKEN"
echo "Then restart Claude Code from a shell where the var is set."
