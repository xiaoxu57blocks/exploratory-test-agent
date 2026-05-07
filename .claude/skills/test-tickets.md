---
name: test-tickets
description: Run the full exploratory-test-agent pipeline on one or more Linear tickets. Usage `/test-tickets SUP-123[,SUP-124,...] [--env=prod|stg]`. Orchestrates linear-fetcher → test-triage → user confirmation → test-strategist → user confirmation → test-executor → linear-reporter. Pauses for user input when triage confidence is medium/low. The default env is prod (writes go to an isolated test tenant).
---

# /test-tickets

You are orchestrating the exploratory-test-agent pipeline. The user has invoked you with a comma-separated list of Linear ticket IDs and optionally an `--env` flag.

## Arguments

- Ticket IDs (required): comma-separated, e.g. `SUP-7152,SUP-7497`
- `--env=prod|stg` (optional, default `prod`)

If no IDs are provided, ask the user for them before doing anything else. Do not invent ticket IDs.

The user may also trigger this with natural language ("测试 SUP-7152, SUP-7497", "test these: ENG-1234"). Treat that the same as the slash command. If the user says an env in natural language ("on staging", "在 stg 环境"), parse that into `env=stg`.

## Pipeline

Execute these phases in order. **Announce each agent invocation before calling it** (per the project's transparency rule).

### Phase 0 — Setup

1. Generate run-id: `<YYYY-MM-DD>_<HHMM>_<first-ticket-id>`. Use `date +%Y-%m-%d_%H%M`.
2. Create `artifacts/<run-id>/` directory.
3. Read `.claude/test-env.local.json`. Verify the chosen env exists and at least the `external` role has non-null credentials. If missing/malformed: print a clear error pointing to the `.example` file and stop.
4. Tell the user: "Run id: `<run-id>`. Env: `<env>`. Artifacts will be at `artifacts/<run-id>/`."

### Phase 1 — Fetch

Invoke the `linear-fetcher` agent with the ticket list and run-id.

After it returns, verify `artifacts/<run-id>/01-fetch.json` exists. If any tickets errored (in `errors[]`), tell the user and ask whether to continue with the rest.

### Phase 2 — Triage

Invoke the `test-triage` agent with the run-id.

After it returns, **read `02-triage.json` yourself** and present a summary table to the user:

```
| Ticket | Decision | Confidence | Role | Reason |
|--------|----------|------------|------|--------|
| SUP-7152 | Test (unit-1) | high | external | Full new case create UX |
| SUP-7497 | Test (unit-1) | high | external | Same milestone as 7152 |
| SUP-9999 | Skip | high | — | label: tech-debt |
```

Then:
- If `needs_user_review` is empty → proceed to Phase 3.
- If `needs_user_review` has items → use `AskUserQuestion` to ask:
  - For test units: "Proceed with testing this unit?" (Yes / Skip / Need more info)
  - For role uncertainty: "Run unit-X as <inferred-role>?" (Yes / Switch to other role)
  - For skipped tickets: "Confirm skip?" (Confirm / Test anyway)
- After user input, update `02-triage.json` with the user's decisions (add a `user_overrides` section, don't rewrite the file).

### Phase 3 — Strategy

For each test unit that survived triage:

1. Announce: "Generating spec for unit-X covering SUP-NNN, SUP-MMM (env=<env>, role=<role>)"
2. Invoke the `test-strategist` agent with the run-id, unit_id, env, and role.
3. After it returns, briefly show the user the generated spec's title, scenario count, and any open questions.

Run units **sequentially**, not in parallel — strategist has shared filesystem state (the artifacts dir).

### Phase 4 — Confirm execution

Before invoking test-executor, ask the user:

> "Specs are ready. Proceed to execute against `<env>` for: <list of units>? This will open Chrome and perform real actions (logins, possibly create test data) in `<env>`."

Include this warning verbatim if env is `prod`:
> "⚠️ This run targets PROD. Ensure the test tenant is isolated. Continue?"

Use `AskUserQuestion` with options: Run all / Run selected / Stop here.

If the user picks "Stop here", proceed to Phase 6 with `mode: "spec-only"` — Linear gets a comment that specs are available without execution.

### Phase 5 — Execute

For each confirmed unit:

1. Announce: "Executing unit-X via Chrome DevTools MCP"
2. Invoke the `test-executor` agent with run-id, unit_id, env, and role.
3. After it returns, show the user a one-line status (PASS/FAIL/error) plus the path to `04-run-<unit_id>/result.json` and `generated.spec.ts` if produced.

Run units **sequentially**. Do not parallelize — they share a Chrome session.

### Phase 6 — Report

Invoke the `linear-reporter` agent with the run-id.

After it returns, show the final summary:

```
Run <run-id> complete (env=<env>).
- N tickets fetched
- X skipped
- Y test units executed: P passed, F failed
- Z Linear comments posted
- Local report: artifacts/<run-id>/05-summary.md

To archive a passing test to portal:
  /archive-to-portal <run-id>/<unit-id>
```

## Hard rules

- **Always pause for user confirmation between phases 2→3 and 4→5.** Browser execution against prod cannot start without an explicit OK.
- **Never skip Phase 2 user review** for medium/low confidence items, even if the user said "do it all" earlier.
- **If any phase fails fatally, stop and tell the user.** Do not silently continue with partial state.
- **Do not call agents in parallel.** This pipeline is intentionally sequential to keep state consistent.
- **Do not invoke `portal-archiver` from this skill.** Archival is a separate, manual step (`/archive-to-portal`) so the user can review `generated.spec.ts` first.

## Anti-patterns

- ❌ Inventing ticket IDs because the user didn't provide any
- ❌ Reading `01-fetch.json` and re-doing triage yourself instead of invoking `test-triage`
- ❌ Auto-confirming Phase 4 because "the user already said yes earlier"
- ❌ Posting to Linear before all units have been executed (or skipped intentionally)
- ❌ Running `prod` without showing the warning prompt
