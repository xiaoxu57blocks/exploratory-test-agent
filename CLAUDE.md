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

The generated `.spec.ts` lives in `artifacts/` (gitignored) until the user explicitly runs `/archive-to-portal`, at which point it is adapted to the `<your-playwright-repo>` repo's conventions and committed on a branch there.

## Companion Repository

`<your-playwright-repo>` (path: `$PLAYWRIGHT_REPO_PATH`) is the canonical Playwright regression suite. It is **not** in the execution path of `/test-tickets` — it is the **archive destination** for tests that pass review.

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
┌────────────────────┐  decides per unit: create_fresh vs reuse_existing case;
│ test-data-planner  │  picks fixtures from manifest by covers_event_types;
└────────────────────┘  auto-adds manifest entries via Drive search when needed
         │  artifacts/<run-id>/02b-data-plan.json
         ▼
┌────────────────────┐  per test unit; binds spec to data plan's case decision
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

### Production safety for internal accounts (highest priority — overrides all other rules)

The internal account on prod has cross-company privileges and can read/write data belonging to companies other than 57blocks / Supio / the designated test company. The blast radius of a single wrong write is real customer data. These rules apply whenever `env=prod` AND `user_role=internal`, and they override any spec, scenario, planner instruction, or user prompt — if those conflict, surface the conflict and refuse to execute, do NOT ask the user to override.

- **Company scope is locked to the test company.** Do not switch tenants/companies via any UI affordance (company switcher, "switch to" link, admin-impersonate flow), URL change (`?company_id=...`, `/companies/<id>/...`), or API call. The session must end the run on the same company it started on.
- **Reads outside the test company are still discouraged but not forbidden.** If the agent inadvertently lands on a non-test-company surface (deep link, redirect), navigate back to the test company immediately and log an `unintended_company_navigation` finding. Do NOT click around.
- **Writes outside the test company are absolutely forbidden.** No update / delete / archive / file upload / field edit / case-state change / comment / status change against any case in any company other than the test company. There is no override.
- **Inside the test company, writes are restricted to `deqtest_`-prefixed cases.** Even within the correct company, the agent must never perform a write operation against a case whose visible display name does not start with `deqtest_`. Other test cases in the tenant may belong to teammates and breaking them costs human time. Read-only navigation of non-`deqtest_` cases is allowed.
- **Pre-write check is mandatory.** Before any state-mutating action under prod-internal, the executor must verify (a) the page is on a URL that belongs to the test company, and (b) the target case's display name starts with `deqtest_`. If either check fails, abort the scenario, mark it FAIL with reason `prod-internal safety check: <which gate failed>`, screenshot the page as evidence, and stop the unit. The orchestrator does not retry, does not prompt the user, does not silently skip — it stops.
- **/create-case is exempt from the deqtest_ check at the moment of clicking Create**, because the case doesn't exist yet — but the case_name being submitted must already start with `deqtest_`, and that's checked before clicking Create. Post-create, the new case naturally satisfies the rule.

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
- This repo **does** write to `$PLAYWRIGHT_REPO_PATH` only during `/archive-to-portal`, never during `/test-tickets`.
- `portal-archiver` creates a branch in the portal repo but never pushes; the user runs `git push` manually after review.

### Linear write operations

- `linear-reporter` is the only agent that writes to Linear, and only via `save_comment`. No state changes, no labels, no relationships, no milestones — only the human ticket owner sets those.
- All comments include the run-id and link to the local report path.
- **Never create relationships between tickets** (`relatedTo`, `blocks`, `blockedBy`, `parentId`, `duplicateOf`, `links`, etc.). Co-occurrence in a `/test-tickets` run is a workflow detail, not a semantic relationship. This rule applies to every agent — if a future agent gets `mcp__linear__save_issue` in its tools, it must explicitly justify why and still must not touch relationship fields.
- **Linear auto-creates "related issue" backlinks from ticket IDs mentioned in comment bodies.** A comment on `LIN-A` containing the literal string `LIN-B` triggers a server-side mention parser that logs an "added related issue" entry on `LIN-B`. No agent permission can prevent this. Mitigation: a comment on `LIN-A` must not contain `LIN-B` unless the comment is genuinely about `LIN-B`'s subject matter. Cross-ticket workflow context belongs in local `05-summary.md`, never in the Linear comment body.

## Agent Roster

| Agent | Kind | Purpose |
|-------|------|---------|
| `linear-fetcher` | sub-agent | Pull ticket data via Linear MCP |
| `test-triage` | sub-agent | Decide test/skip, cluster tickets into units, infer user role |
| `test-data-planner` | sub-agent | Decide create-fresh vs reuse-existing case per unit; pick fixtures by event-type coverage |
| `test-strategist` | sub-agent | Produce Requirement Spec per test unit |
| `test-executor` | **in-context runbook** | Drive Chrome via Chrome DevTools MCP, record trace, generate `.spec.ts`. NOT a sub-agent — orchestrator follows `.claude/agents/test-executor.md` in the main session. See that file for why and don't try to revert. |
| `linear-reporter` | sub-agent | Post results back to Linear (per-unit + aggregate modes) |
| `portal-archiver` | sub-agent | Adapt `generated.spec.ts` to portal repo, create branch |

Each agent's tools, inputs, and detailed rules live in its own `.claude/agents/<name>.md` — do not duplicate them here.

## Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/test-tickets` | `/test-tickets SUP-XXX[,SUP-YYY,...] [--env=prod\|stg]` | Main pipeline (fetch → triage → spec → execute → report) |
| `/archive-to-portal` | `/archive-to-portal <run-id>/<unit-id>` | Manual: ship `generated.spec.ts` to portal repo on a branch |
| `/create-case` | `/create-case [case-name] [--kind <type>] [--add <fixture>]` | Create a fresh AI-artifact-first test case in the Portal with fixture upload; called by executor during data-setup phase |
| `/switch-account` | `/switch-account --role internal\|external [--env prod\|stg]` | Switch the logged-in Portal account mid-run via the avatar-menu logout; preserves localStorage feature-flag overrides |
| `/toggle-feature-flag` | `/toggle-feature-flag --flag <name> on\|off` | Enable or disable a Portal feature flag via localStorage override + reload; checks backend entitlement first and refuses if the flag is not granted server-side |
| `/retro` | `/retro <run-id>` | Post-run retrospective: reads `interventions.jsonl`, identifies agent behavior gaps, and writes `06-retro.md` with concrete fix proposals per agent/skill/template file |

### Trigger styles

`/test-tickets` is the canonical entry. The user may also trigger the same flow with natural language — when the user says something like "测试 SUP-7152, SUP-7497" or "test these tickets: ENG-1234", treat it as `/test-tickets <comma-separated-ids>` and invoke the skill.

## Environment

Required configuration (all in gitignored local files):

| File | Purpose |
|---|---|
| `.claude/settings.local.json` | `PLAYWRIGHT_REPO_PATH` env var, additional dirs |
| `.claude/test-env.local.json` | Test URLs + credentials per env (stg, prod) per role (internal, external) |

Each has a corresponding `.example` checked in. **Both files are required**; the agent must error early with a clear message if either is missing or malformed.

The Linear MCP server uses OAuth on first run; no API token needed. Ticket IDs already carry their team prefix (e.g. `SUP-7152`), so a single workspace can mix tickets from any team.

## What This Repo is NOT

- Not a permanent home for Playwright code — generated specs live in `artifacts/` and are archived to portal only on demand.
- Not a long-running service — every invocation is a one-shot run triggered manually.
- Not a debugging environment for portal regressions — debug those in `portal-ui-automation`.

## Common Operations

```bash
./scripts/verify-mcp.sh                                # smoke-check Linear MCP
ls artifacts/<run-id>/                                 # inspect a run's artifacts
> /archive-to-portal <run-id>/<unit-id>                # ship passing test to portal (manual)
> /retro <run-id>                                      # post-run retro → artifacts/<run-id>/06-retro.md

# Fixture management
python3 scripts/get-fixture.py --list                  # list all fixtures in manifest
python3 scripts/get-fixture.py --name "MRnMB.pdf"     # download fixture to cache

# Artifact validation (run after executor writes result.json / trace.jsonl)
python3 scripts/validate-artifact.py --kind result --path artifacts/<run-id>/04-run-unit-1/result.json
python3 scripts/validate-artifact.py --kind trace  --path artifacts/<run-id>/04-run-unit-1/trace.jsonl

# First-time setup
./scripts/install-shell-hooks.sh                       # auto-load .claude/settings.local.json env on cd
python3 scripts/google-drive.py auth                   # authenticate Google Drive for fixture downloads
```

## Why This Architecture

- **Agent-first execution**: an LLM that looks at the page and decides the next action is more robust to UI variation than pre-written selectors.
- **Playwright as the artifact, not the runtime**: trace → `.spec.ts` happens only after the test passes, so what gets archived is a known-working recording.
- **Reviewed archival**: portal stays clean because nothing lands there until a human approves.
- **Confidence gating**: triage is honest about uncertainty (Linear data is incomplete) rather than guessing.
