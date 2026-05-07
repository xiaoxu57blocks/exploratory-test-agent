# CLAUDE.md

This file is the operating manual for the **exploratory-test-agent** project. Claude Code reads it on every session to understand how to behave in this repository.

## Project Purpose

`exploratory-test-agent` is a **test agent** that performs LLM-driven exploratory testing — instead of running pre-written scripts, it looks at the page, decides the next action, and adapts to UI variation. It takes Linear ticket IDs, decides which need E2E testing, plans the test strategy, **executes the tests in a real browser via the Chrome DevTools MCP**, and reports results back to Linear.

Inputs: Linear ticket IDs.
Outputs:
1. A triage report (which tickets need testing, why, what user role)
2. A test strategy and Requirement Spec for each test unit
3. **An executed test run** — screenshots, trace, pass/fail per scenario
4. **A generated Playwright `.spec.ts` file** as a side-effect of the run (the executor records every step it took, then translates the trace into Playwright code)
5. A comment posted on each ticket summarizing results

The generated `.spec.ts` lives in `artifacts/` (gitignored) until the user explicitly runs `/archive-to-portal`, at which point it is adapted to the [portal-ui-automation](https://github.com/codeseals/portal-ui-automation) repo's conventions and committed on a branch there.

## Companion Repository

[portal-ui-automation](https://github.com/codeseals/portal-ui-automation) (path: `$PORTAL_REPO_PATH`) is the canonical Playwright regression suite. It is **not** in the execution path of `/test-tickets` — it is the **archive destination** for tests that pass review.

## Pipeline Overview

```
User: /test-tickets SUP-7152,SUP-7497 [--env=stg|prod]
         │
         ▼
┌────────────────────┐
│ linear-fetcher     │  reads Linear via MCP
└────────────────────┘
         │  artifacts/<run-id>/01-fetch.json
         ▼
┌────────────────────┐  rule-based + LLM triage
│ test-triage        │  outputs: skip vs test, clusters,
└────────────────────┘  inferred user_role (default: external)
         │  artifacts/<run-id>/02-triage.json
         ▼
   USER CONFIRMATION (medium/low confidence + role inference)
         │
         ▼
┌────────────────────┐  per test unit
│ test-strategist    │  produces Requirement Spec
└────────────────────┘  (env, role, scenarios, preconditions)
         │  artifacts/<run-id>/03-spec-<unit>.md
         ▼
┌────────────────────┐  drives Chrome via Chrome DevTools MCP
│ test-executor      │  records every step (trace.jsonl)
└────────────────────┘  takes screenshots, evaluates assertions
         │  artifacts/<run-id>/04-run-<unit>/
         │    ├── trace.jsonl
         │    ├── screenshots/
         │    ├── generated.spec.ts    (Playwright translation)
         │    └── result.json
         ▼
   USER REVIEW (results + generated.spec.ts)
         │
         ▼
┌────────────────────┐  posts comment on each ticket
│ linear-reporter    │  with results + screenshots + run-id
└────────────────────┘

   Optional, manual:
   /archive-to-portal <run-id>/<unit-id>
         │
         ▼
┌────────────────────┐  copies generated.spec.ts into portal repo,
│ portal-archiver    │  fits it to portal's structure (pages/, fixtures),
└────────────────────┘  creates a branch — never auto-pushes
```

## Hard Rules

### Confidence gating

- `test-triage` classifies each ticket as `high` / `medium` / `low` confidence.
- `medium` and `low` confidence tickets must be presented to the user for confirmation before proceeding.
- The inferred `user_role` (internal / external) must also be confirmed when not derivable with high confidence from the ticket. Default is `external`.
- Never silently skip a ticket — every skipped ticket must have a written reason.

### Test environment

- The default execution environment is **prod**. STG can be selected with `--env=stg`.
- Real credentials live in `.claude/test-env.local.json` (gitignored). A template `test-env.local.json.example` is checked in.
- Both `internal` and `external` user accounts are required per environment, but the spec/triage decides which role each unit needs (default external).
- The agent reads credentials from the local config file at runtime and **never echoes passwords into chat, logs, artifacts, or commit messages**.
- Production tests run against an **isolated test tenant** — writes do not affect real customer data.

### Artifacts directory

- Every run creates a unique directory: `artifacts/<YYYY-MM-DD_HHMM>_<first-ticket-id>/`.
- All intermediate JSON, specs, traces, screenshots, generated code go here.
- `artifacts/` is gitignored — it is local working state, not source.

### Cross-repo boundary

- This repo **never** imports from `portal-ui-automation`.
- This repo **does** write to `$PORTAL_REPO_PATH` only during `/archive-to-portal`, never during `/test-tickets`.
- `portal-archiver` creates a branch in the portal repo but never pushes; the user runs `git push` manually after review.

### Linear write operations

- `linear-reporter` is the only agent that writes to Linear (comments).
- Never change ticket state automatically. Only post comments.
- All comments include the run-id and link to the local report path.

## Agent Roster

| Agent | Purpose | Tools |
|-------|---------|-------|
| `linear-fetcher` | Pull ticket data via Linear MCP | `mcp__linear__*`, Read, Write |
| `test-triage` | Decide test/skip, cluster, infer user role | Read, Write, Grep |
| `test-strategist` | Produce Requirement Spec per test unit | Read, Write |
| `test-executor` | Run the test in Chrome via Chrome DevTools MCP, record trace, generate .spec.ts | `mcp__chrome-devtools__*`, Read, Write, Bash |
| `portal-archiver` | Adapt generated.spec.ts to portal repo, create branch | Bash, Read, Write |
| `linear-reporter` | Post results back to Linear | `mcp__linear__*`, Read |

## Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/test-tickets` | `/test-tickets SUP-XXX[,SUP-YYY,...] [--env=prod\|stg]` | Main pipeline (fetch → triage → spec → execute → report) |
| `/archive-to-portal` | `/archive-to-portal <run-id>/<unit-id>` | Manual: ship `generated.spec.ts` to portal repo on a branch |

### Trigger styles

`/test-tickets` is the canonical entry. The user may also trigger the same flow with natural language — when the user says something like "测试 SUP-7152, SUP-7497" or "test these tickets: ENG-1234", treat it as `/test-tickets <comma-separated-ids>` and invoke the skill.

## Environment

Required configuration (all in gitignored local files):

| File | Purpose |
|---|---|
| `.claude/settings.local.json` | `PORTAL_REPO_PATH` env var, additional dirs |
| `.claude/test-env.local.json` | Test URLs + credentials per env (stg, prod) per role (internal, external) |

Each has a corresponding `.example` checked in. **Both files are required**; the agent must error early with a clear message if either is missing or malformed.

The Linear MCP server uses OAuth on first run; no API token needed. Ticket IDs already carry their team prefix (e.g. `SUP-7152`), so a single workspace can mix tickets from any team.

## What This Repo is NOT

- Not a permanent home for Playwright code — generated specs live in `artifacts/` and are archived to portal only on demand.
- Not a long-running service — every invocation is a one-shot run triggered manually.
- Not a debugging environment for portal regressions — debug those in `portal-ui-automation`.

## Common Operations

```bash
# Verify Linear MCP is working
./scripts/verify-mcp.sh

# Run pipeline (prod, default)
> /test-tickets SUP-7152,SUP-7497

# Run pipeline on STG
> /test-tickets SUP-7152 --env=stg

# Natural language equivalent
> 测试 SUP-7152, SUP-7497

# Inspect a run
ls artifacts/2026-05-07_1430_SUP-7152/

# Archive a passing test to portal (manual, after reviewing generated.spec.ts)
> /archive-to-portal 2026-05-07_1430_SUP-7152/unit-1
```

## Why This Architecture

- **Agent-first execution**: an LLM driving Chrome DevTools MCP can adapt step-by-step (look at the screenshot, decide the next action) — far more robust to UI variation than pre-written selectors.
- **Playwright as the artifact, not the runtime**: the trace captured during execution is translated to `.spec.ts` only after the test passes — so what gets archived is a recording of a *known-working* path, not a guess.
- **Reviewed archival, not automatic ingestion**: portal stays clean because nothing lands there until a human approves.
- **Confidence gating**: Linear data is incomplete; the triage agent must be honest about uncertainty rather than guess.
