# exploratory-test-agent

> **Turn Linear tickets into executed E2E tests, then archive the recording — not the guess.**

An LLM-driven exploratory testing agent that takes ticket IDs, drives a real browser end-to-end against your app, and only after a test actually passes does it generate a Playwright `.spec.ts`. The generated spec is therefore a **recording of a known-working path**, not pre-written selectors against assumptions.

Built on [Claude Code](https://claude.com/claude-code) using its agent + skill primitives. Writes a comment back to each Linear ticket with screenshots and a result summary.

> **Status: POC.** Run small batches, review every stage, expect the agent to ask before doing anything irreversible.

---

## Why this exists

Traditional Playwright suites are written **ahead of time** against assumptions about the DOM. They break the moment the UI shifts and need constant maintenance. They also don't help you triage a ticket — they tell you whether a known flow still works, not whether _this specific change_ in PR #1234 actually does what the ticket said it would.

This agent flips both:

1. **The agent looks at the page** (DOM snapshot + screenshot) and decides the next click on the fly. UI variation is far easier to absorb at run-time than to pre-encode.
2. **The agent reads the linked PR's diff** (via the GitHub MCP) before writing scenarios. It tests what the PR _actually shipped_, not what the ticket prose promised.
3. **Playwright is the artifact, not the runtime.** A run translates a successful trace into `.spec.ts` only after every primary scenario passes. A failing run produces screenshots + result + Linear comment; no spec, because a broken recording is worse than no recording.

---

## How it works

### Pipeline

```
ticket IDs ──▶ fetch ──▶ triage ──▶ [confirm] ──▶ spec ──▶ execute ──▶ [review] ──▶ report ──▶ Linear comment
                                                              │
                                                       (drives Chrome
                                                        via MCP, records
                                                        every step)
                                                              │
                                                              ▼
                                                  generated.spec.ts (only on PASS)
                                                              │
                                                  optional, manual:
                                                  /archive-to-portal ──▶ <your-playwright-repo> branch
```

### The six agents

| Agent | Job | Reads | Writes |
|---|---|---|---|
| `linear-fetcher` | Pull ticket bodies, comments, attachments | Linear MCP | `01-fetch.json` |
| `test-triage` | Decide test/skip per ticket; cluster into units; infer user role | `01-fetch.json` | `02-triage.json` |
| `test-strategist` | Read each linked PR's diff and write a Requirement Spec grounded in shipped code | `02-triage.json`, GitHub MCP | `03-spec-<unit>.md` + `.json` sidecar |
| `test-executor` | Drive Chrome step-by-step; record every action; evaluate Then-clauses | `03-spec-<unit>.json`, Chrome DevTools MCP | `trace.jsonl`, `screenshots/`, `result.json`, `generated.spec.ts` |
| `linear-reporter` | Post a comment to each ticket with the result + screenshots | `result.json` | Linear comment |
| `portal-archiver` | (Manual) Adapt `generated.spec.ts` to your Playwright repo's conventions on a branch | `generated.spec.ts` | branch in `<your-playwright-repo>` |

### Confidence gating

Linear data is incomplete. Every triage decision carries a `high` / `medium` / `low` confidence and an inferred user role. Medium and low decisions, plus any ambiguous role inference, are surfaced for explicit user confirmation. **No ticket is silently skipped** — every skip carries a written reason in `02-triage.json`.

### Schema-validated artifacts

Every run lands a directory under `artifacts/<run-id>/` (gitignored). The pipeline phases hand off through files, not in-memory message passing — each artifact is JSON Schema-validated by `scripts/check-phase.py` between phases, so a malformed hand-off stops the pipeline early instead of poisoning downstream agents:

```
artifacts/<run-id>/
├── 01-fetch.json              # raw Linear data
├── 02-triage.json              # decisions + confidence per ticket
├── 03-spec-<unit>.md          # Requirement Spec (human-readable)
├── 03-spec-<unit>.json        # same spec, machine-readable (the contract executor reads)
└── 04-run-<unit>/
    ├── trace.jsonl            # one JSON object per step (schema-validated)
    ├── screenshots/           # PNGs at every checkpoint + on every failure
    ├── result.json            # pass/fail per scenario (schema-validated)
    └── generated.spec.ts      # Playwright translation — only on PASS
```

Schemas live in [`schemas/`](./schemas/); the validator is `scripts/validate-artifact.py`.

### Reviewed archival

`<your-playwright-repo>` (the canonical regression suite) stays clean: nothing lands there until you explicitly run `/archive-to-portal` and review the diff. This repo never pushes to it.

### Credentials never leave the box

Test creds are read once at the start of a run and kept in agent-local memory. Passwords are masked before screenshots, never appear in `trace.jsonl` / `result.json` / `generated.spec.ts` / chat. The generated spec references env-var placeholders, never inline values.

---

## Quickstart

### Prerequisites

- [Claude Code](https://claude.com/claude-code)
- Node 20+ (for `npx mcp-remote`)
- Python 3.11+ (helper scripts; stdlib only)
- Chrome
- Linear workspace + tickets to test
- GitHub PAT for the repo whose PRs your tickets reference
- Google account with access to the team's fixture Drive folder
- _(optional)_ a Playwright repo to archive passing tests into — the `<your-playwright-repo>` of your project

Full step-by-step setup (4 MCP servers + OAuth dances) is in **[docs/SETUP.md](./docs/SETUP.md)**. Plan ~20 minutes the first time.

### Run a test

Inside a Claude Code session in this repo:

```
> /test-tickets LIN-123,LIN-456
```

Defaults to **prod**. Use `--env=stg` to switch. Natural language works too — `测试 LIN-123, LIN-456` is treated the same.

The agent pauses for **user confirmation** twice:

1. After triage, when any ticket is medium/low confidence or its user role can't be inferred.
2. After execution, before reporting back to Linear, so you can review screenshots and the generated spec.

### Inspect a run

Open `artifacts/<run-id>/` — every artifact is plain JSON or markdown. The Linear comment links back to it.

### Archive a passing test

After reviewing `generated.spec.ts`:

```
> /archive-to-portal 2026-05-07_1430_LIN-123/unit-1
```

Adapts the spec to your Playwright repo's structure (pages/, fixtures, naming) and creates a branch. **It never pushes** — review the diff and `git push` yourself.

---

## Project layout

```
.claude/
  agents/                # one .md per sub-agent — these are the prompts
  skills/                # /test-tickets, /archive-to-portal, /create-case
  settings.json          # checked-in: permissions allowlist, MCP servers
  settings.local.json    # gitignored: per-developer paths, secrets
  test-env.local.json    # gitignored: test-tenant credentials
artifacts/               # gitignored: per-run outputs
fixtures/
  manifest.json          # checked-in: fixture name → Drive file id mapping
  cache/                 # gitignored: downloaded PDFs
schemas/                 # JSON Schemas for spec / trace / result
scripts/
  attach-screenshot-to-comment.py   # compress + upload + delete attachment shim
  check-phase.py                    # orchestrator pre-flight between phases
  get-fixture.py                    # name → cached file via Drive API
  google-drive.py                   # OAuth client + find/download
  validate-artifact.py              # schema validator
  verify-mcp.sh                     # Linear MCP OAuth bootstrap
docs/
  SETUP.md
CLAUDE.md                # operating manual the agents read on every session
```

## Hard rules at a glance

- **No silent skips.** Every skipped ticket has a written reason.
- **No production writes outside the test tenant.** Configured per-env in `test-env.local.json`.
- **Linear-side relationships are the human owner's job.** This agent posts comments and nothing else — never `relatedTo` / `blocks` / `parentId`.
- **No reload during a scenario unless the spec demands it.** Reload destroys evidence of "things that should update live but didn't"; that class of bug needs an explicit non-reload observation first.
- **Spec is grounded in PR diffs, not ticket prose.** When the ticket promises X but the PR doesn't ship X, that's an Open question, not a scenario.

Full operating manual for agent-side rules: **[CLAUDE.md](./CLAUDE.md)**.

## License

TBD.
