# exploratory-test-agent

A Claude Code-powered agent that turns Linear tickets into executed E2E tests — and only after a test actually passes does it generate a Playwright `.spec.ts`.

You give it ticket IDs. It fetches them, decides which need testing, plans each one, **drives a real Chrome via the Chrome DevTools MCP** to run the test, then posts results back to Linear. Generated Playwright code is a *recording of a known-working path*, not a guess written ahead of time.

## How to use it

### 1. One-time setup

Prereqs:
- Node 20+ (for `npx mcp-remote`)
- [Claude Code](https://claude.com/claude-code) installed
- Chrome installed locally (the executor launches it via Chrome DevTools MCP)
- Linear access; `portal-ui-automation` cloned somewhere on disk if you plan to archive tests

Copy and fill the two local config files (both gitignored):

```bash
cp .claude/settings.local.json.example .claude/settings.local.json
cp .claude/test-env.local.json.example .claude/test-env.local.json
```

In [.claude/settings.local.json](.claude/settings.local.json) set `PORTAL_REPO_PATH` to your local clone of [portal-ui-automation](https://github.com/codeseals/portal-ui-automation).

In [.claude/test-env.local.json](.claude/test-env.local.json) fill in `stg` and `prod` URLs plus internal/external test accounts. **These are real credentials** — the agent reads them at run time and never echoes them to chat, logs, artifacts, or commits. Production tests run against an isolated test tenant; they do not touch real customer data.

Verify Linear MCP (first run prompts OAuth in your browser):

```bash
./scripts/verify-mcp.sh
```

### 2. Run

Inside the repo, start a Claude session and trigger the pipeline:

```
> /test-tickets SUP-7152,SUP-7497
```

Defaults to **prod**. Use `--env=stg` to switch. Natural language works too — `测试 SUP-7152, SUP-7497` is treated the same.

The agent will pause for **user confirmation** twice in the typical run:
1. After triage, when any ticket is medium/low confidence or its user role can't be inferred
2. After execution, before reporting back to Linear, so you can review screenshots and the generated spec

### 3. Inspect a run

Each run gets a unique directory under `artifacts/` (gitignored):

```
artifacts/<YYYY-MM-DD_HHMM>_<first-ticket-id>/
├── 01-fetch.json              # raw Linear data
├── 02-triage.json              # test/skip decisions, confidence, reasoning
├── 03-spec-<unit_id>.md        # Requirement Spec per test unit
└── 04-run-<unit_id>/
    ├── trace.jsonl             # one JSON line per executed step
    ├── screenshots/            # PNGs at every checkpoint + on every failure
    ├── result.json             # pass/fail per scenario
    └── generated.spec.ts       # Playwright translation — only written if all primary scenarios passed
```

### 4. Archive a passing test (manual)

Generated specs stay local until you say so. After reviewing `generated.spec.ts`:

```
> /archive-to-portal 2026-05-07_1430_SUP-7152/unit-1
```

That copies the spec into your `portal-ui-automation` clone, adapts it to that repo's `pages/` + fixtures structure, and creates a branch. **It never pushes** — you review the diff and `git push` yourself.

## Design思路

A few decisions that shape the whole pipeline:

**LLM-driven execution beats pre-written selectors.** A subagent looking at the actual page (DOM snapshot + screenshot) can decide the next click on the fly. That's far more robust to UI variation than a Playwright file written ahead of time against assumptions about the DOM. So the agent *executes first*, in a real browser, and only writes Playwright code from the trace of what worked.

**Playwright is the artifact, not the runtime.** The trace captured during execution is translated to `.spec.ts` only after **all `[primary]` scenarios pass**. What gets archived is therefore a recording of a known-working path. A failing run produces screenshots, a result file, and a Linear comment — but no spec, because a broken recording is worse than no recording.

**Reviewed archival, not automatic ingestion.** `portal-ui-automation` is the canonical regression suite and stays clean: nothing lands in it until a human runs `/archive-to-portal` and reviews the diff. `exploratory-test-agent` never pushes to portal.

**Confidence gating.** Linear tickets are often incomplete. The triage agent classifies each ticket `high`/`medium`/`low` and surfaces every medium/low decision (and any ambiguous user-role inference) for explicit user confirmation. No ticket is silently skipped — every skip carries a written reason in `02-triage.json`.

**Hard separation between read and write to Linear.** Only `linear-reporter` writes (and only as comments — never status changes). Every other agent reads. Comments always include the run id and link back to the local report so you can trace evidence.

**Credentials never leave the box.** Read once at the start of the run, kept in agent-local memory, used only for the login step. Passwords are masked before screenshots are taken, never appear in `trace.jsonl`, `result.json`, `generated.spec.ts`, or chat. The generated spec references `process.env.SUPIO_USERNAME` / `process.env.SUPIO_PASSWORD` placeholders, never inline values.

## Pipeline at a glance

```
fetch → triage → [confirm] → spec → execute (Chrome via MCP) → [review] → report to Linear
                                                                           ↓
                                                         optional, manual: archive to portal
```

Per-stage detail, hard rules, and agent contracts live in [CLAUDE.md](CLAUDE.md).

## Status

POC. Run small batches, review every stage, expect the agent to ask before doing anything irreversible.
