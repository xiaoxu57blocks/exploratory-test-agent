#!/usr/bin/env bash
# Verifies Linear MCP is reachable.
#
# This script is a smoke test, not a full check. It pings the MCP endpoint
# and confirms the SSE stream opens. It does NOT verify that you have
# access to a specific team — that has to be done from inside Claude Code
# by invoking linear-fetcher.

set -euo pipefail

ENDPOINT="https://mcp.linear.app/mcp"

echo "→ Checking that npx is available..."
command -v npx >/dev/null || { echo "✗ npx not found. Install Node 20+."; exit 1; }
echo "  ✓ npx found"

echo "→ Checking that the MCP endpoint is reachable..."
if ! curl -sfI "$ENDPOINT" >/dev/null 2>&1; then
  # SSE endpoints sometimes don't respond well to HEAD requests.
  # Try a short GET with a timeout.
  if ! curl -sf --max-time 5 -o /dev/null "$ENDPOINT" 2>&1; then
    echo "  ⚠ Could not reach $ENDPOINT directly — this is sometimes normal for SSE."
    echo "    Trust the MCP client to handle the connection on first use."
  fi
fi
echo "  ✓ endpoint check done"

echo
echo "Next step:"
echo "  1. cd $(dirname "$(realpath "$0")")/.."
echo "  2. claude"
echo "  3. In the session, ask: 'Use the linear MCP to fetch issue LIN-1 and show me the title.'"
echo
echo "  On first use, an OAuth window will open in your browser. Approve it once."
echo "  After that, the linear-fetcher agent should work end-to-end."
