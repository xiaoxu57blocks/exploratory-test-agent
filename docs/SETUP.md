# Setup

End-to-end setup for `exploratory-test-agent`. Plan ~20 minutes the first time. After this, day-to-day usage is just `/test-tickets <ticket-ids>` inside a Claude Code session.

## Prerequisites

You'll need:

- **[Claude Code](https://claude.com/claude-code)** — the runtime. The agent ships as a bundle of `.claude/agents/`, `.claude/skills/`, and `scripts/` that Claude Code reads. No other CLI to install.
- **Node 20+** — needed by `npx mcp-remote`, the OAuth-aware proxy that connects Claude Code to remote MCP servers (Linear and GitHub here).
- **Python 3.11+** — runs the local helper scripts (`scripts/*.py`). Standard library only; no `pip install`.
- **Chrome** — the executor drives a real browser via the [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp). Stable channel works.
- **A Google account with access to your team's fixture Drive folder** — used to download test fixtures (PDFs etc.) into a new case during scenarios that need a fresh case.
- **A Linear workspace** with the tickets you want to test.
- **A GitHub account** with read access to the repo whose PRs the tickets reference. Required so the strategist can read PR diffs and ground scenarios in actual code.
- **(Optional) A Playwright repo** to archive passing tests into. Only needed if you plan to run `/archive-to-portal`; standard `/test-tickets` runs ignore it.

## 1. Local config files

Both files are gitignored — never commit them.

```bash
cp .claude/settings.local.json.example .claude/settings.local.json
cp .claude/test-env.local.json.example .claude/test-env.local.json
```

### `.claude/settings.local.json`

Two fields you'll set:

- `env.PLAYWRIGHT_REPO_PATH` — absolute path to your local clone of `<your-playwright-repo>` (the destination for `/archive-to-portal`). Leave the example value if you don't plan to archive yet.
- `env.GITHUB_PERSONAL_ACCESS_TOKEN` — a classic PAT, see § 3 below.

### `.claude/test-env.local.json`

Real credentials for the test tenant. Per environment (`stg`, `prod`), per role (`internal`, `external`), with `username` and `password`. The agent reads these at run-time and never echoes them to chat, logs, artifacts, or commits. Production tests run against an isolated test tenant; they do not touch real customer data.

## 2. Linear MCP

Linear MCP is a remote OAuth server. First time you run any agent that talks to Linear, `mcp-remote` opens your browser for consent and caches the token under `~/.mcp-auth/`. After that, infinite uses without re-authing.

```bash
./scripts/verify-mcp.sh
```

Walks through the OAuth flow if needed, then prints connected MCP servers. Expected output ends with `linear: ... ✓ Connected`.

## 3. GitHub MCP

The strategist reads PR diffs to ground scenarios in shipped code. The MCP for that uses GitHub's classic personal access token.

1. Go to <https://github.com/settings/tokens/new> (the **classic** PAT page; not fine-grained).
2. **Note**: e.g. `claude-code-exploratory-test-agent`. Expiration: 90 days or what you're comfortable with.
3. **Scopes**: tick `repo`. That's all — `read:org` is optional.
4. **Generate token**. Copy the `ghp_...` value once (it disappears on refresh).
5. Paste it into `.claude/settings.local.json` under `env.GITHUB_PERSONAL_ACCESS_TOKEN`.
6. If your org enforces SAML SSO, the new token page has a "Configure SSO" link; click it and authorize the org.

The MCP server is added by:

```bash
claude mcp add github npx -e GITHUB_PERSONAL_ACCESS_TOKEN=$(jq -r '.env.GITHUB_PERSONAL_ACCESS_TOKEN' .claude/settings.local.json) -- -y @modelcontextprotocol/server-github
```

(Re-run this if you rotate the token — the env var is captured into the MCP server config at add-time, not read live.)

Verify with `claude mcp list` — `github` should report `✓ Connected`. If you see HTTP 401, the PAT didn't authorize the org yet.

## 4. Chrome DevTools MCP

Driven entirely from MCP — no local browser config to touch. First run installs the package on demand:

```bash
claude mcp add chrome-devtools npx -- -y chrome-devtools-mcp@latest
```

Verify with `claude mcp list` — should report `✓ Connected`. The actual Chrome window only opens when an executor scenario starts.

## 5. Google Drive (for fixture downloads)

The `/create-case` skill pulls fixtures from a Google Drive folder you have access to. Drive content is access-controlled, so the helper uses OAuth — no service account, no public links.

You need a **Desktop OAuth client** in a Google Cloud project. If your team already has a shared GCP project for this agent, reuse it; otherwise create a new one (any name).

### One-time GCP setup

In <https://console.cloud.google.com>:

1. **Create or select a project.** Any name; you only need one across the team.
2. **Enable the Google Drive API**: APIs & Services → Library → search "Google Drive API" → Enable.
3. **Configure the OAuth consent screen**: APIs & Services → OAuth consent screen.
   - User type: **External**.
   - App name: anything (`exploratory-test-agent` is fine).
   - User support email + Developer contact: your email.
   - Scopes: add `https://www.googleapis.com/auth/drive.readonly`.
   - Test users: add your Google account email (and any teammate who'll use this).
4. **Create the OAuth client**: APIs & Services → Credentials → Create credentials → OAuth client ID → **Application type: Desktop app** → Create → Download JSON.
5. Save the downloaded file to `.claude/google-oauth-client.json` (gitignored).

The OAuth client itself can be shared across the team — Google's docs explicitly note "client secrets for installed apps are not really secrets". The cached *token* is per-user.

### One-time auth flow

```bash
scripts/google-drive.py auth
```

Opens your browser, asks you to grant `drive.readonly`, then caches the token to `.claude/google-oauth-token.json` (gitignored, mode 0600). Refresh-token flow takes over from here — you won't see the consent screen again unless you revoke access in your Google account settings.

### Sanity check

```bash
scripts/get-fixture.py --name "<a-fixture-name-from-fixtures/manifest.json>"
# → {"ok": true, ..., "from_cache": false, "size": ...}
```

If you see `{"ok": false, "exit_code": 4}`, the cached token is missing — re-run the `auth` step.

## 6. Smoke test the whole pipeline

In a Claude Code session in this repo:

```
> /test-tickets <a-ticket-id-with-an-attached-PR>
```

Pick a ticket whose PR is small (UI-only, < 500 lines) for the first run. The agent will pause for confirmation twice — after triage, and before posting back to Linear — so you can abort if anything looks wrong.

## Troubleshooting

- **MCP server `✗ Failed to connect`** after `claude mcp list` — most often an auth issue. Linear's OAuth dance can fail if a popup blocker stops the browser; re-run `./scripts/verify-mcp.sh`. GitHub PAT errors are visible in the server's stderr (`tail -n 50 ~/.config/claude-cli/logs/...`).
- **`scripts/google-drive.py` returns `403: Drive API has not been used in project ...`** — you skipped step 2 above. Click the URL the error prints, hit Enable, wait 30 seconds, retry.
- **Chrome window never opens during a run** — Chrome DevTools MCP launches Chrome on demand from the executor; if the executor never invokes a `chrome-devtools-mcp` tool (e.g. it aborted during pre-flight), no window appears. Look at `artifacts/<run-id>/04-run-<unit>/trace.jsonl` for the abort line.
- **Permission prompts for routine commands** — Claude Code's permission allowlist is in `.claude/settings.json`. The repo's defaults cover most needs; add specific patterns to your `.claude/settings.local.json` if your workflow keeps tripping the same prompt.
