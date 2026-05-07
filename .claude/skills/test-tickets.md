---
name: test-tickets
description: Run the full exploratory-test-agent pipeline on one or more Linear tickets. Usage `/test-tickets SUP-123[,SUP-124,...] [--env=prod|stg]`. Orchestrates linear-fetcher → test-triage → test-strategist → test-executor → linear-reporter end-to-end without user prompts on the happy path. Only pauses when triage confidence is medium/low or a spec produces `open_questions`. The default env is prod (writes go to an isolated test tenant configured in test-env.local.json).
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
3. **Touch the active marker**: `touch artifacts/<run-id>/.active`. The intervention-logging hook (`.claude/hooks/log-intervention.sh`) only writes to `interventions.jsonl` while exactly one such marker exists; without this touch, no interventions will be captured for the run.
4. Read `.claude/test-env.local.json`. Verify the chosen env exists and at least the `external` role has non-null credentials. If missing/malformed: print a clear error pointing to the `.example` file and stop.
5. Tell the user: "Run id: `<run-id>`. Env: `<env>`. Artifacts will be at `artifacts/<run-id>/`."

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

### Phase 5 — Execute

For each confirmed unit:

1. Announce: "Executing unit-X via Chrome DevTools MCP"
2. Invoke the `test-executor` agent with run-id, unit_id, env, and role.
3. After it returns, show the user a one-line status (PASS/FAIL/error) plus the path to `04-run-<unit_id>/result.json` and `generated.spec.ts` if produced.

Run units **sequentially**. Do not parallelize — they share a Chrome session.

### Phase 6 — Report

Invoke the `linear-reporter` agent with the run-id.

After it returns, **remove the active marker**: `rm artifacts/<run-id>/.active`. From this point on, further user prompts will not be appended to this run's `interventions.jsonl` — they belong to whatever conversation comes next, not to this test run.

Show the final summary:

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

- **Pause for user confirmation between phases 2→3 only when triage produced `needs_user_review` items.** A clean high-confidence triage proceeds straight through. Phase 4 (confirm-before-execute) was removed: with `prod.external` in `test-env.local.json` always pointing at the isolated test tenant, and with the run-id printed at Phase 0, the previous prod warning was friction without protection.
- **Never skip Phase 2 user review** for medium/low confidence items, even if the user said "do it all" earlier.
- **If any phase fails fatally, stop and tell the user.** Do not silently continue with partial state.
- **Do not call agents in parallel.** This pipeline is intentionally sequential to keep state consistent.
- **Do not invoke `portal-archiver` from this skill.** Archival is a separate, manual step (`/archive-to-portal`) so the user can review `generated.spec.ts` first.

### Orchestrator note duty (powers `/retro`)

The intervention-logging hook captures every user prompt verbatim, but it can't see *what the orchestrator did in response*. Whenever you (the orchestrator) make a non-trivial course correction during a run — e.g. you re-scope a spec mid-flight, you stop dispatching to a sub-agent and drive the work yourself, you toggle a runtime flag because the spec didn't catch it, you switch surfaces (legacy AI assistant → case agent), or you change which env/account is used — append a single JSONL line to `artifacts/<run-id>/interventions.jsonl` so that `/retro` can pair the user's prompt with what changed downstream.

Format:

```json
{"ts":"<ISO8601 UTC>","kind":"orchestrator_note","phase":"5b","trigger":"user said 'OAuth已经做过了'","decision":"narrowed spec to disconnect/reconnect cycle only; rewrote 03-spec-unit-1.md","why":"matched spec to actual test data state to avoid blocked scenarios"}
```

Rules:
- Only log notes that would matter to a future retro — i.e. the kind of thing that, in hindsight, suggests an agent or skill should have done it without prompting. Routine "I picked option A from the AskUserQuestion you presented" is NOT a note; the hook already captured the prompt and the option chosen is in your reply.
- Keep `decision` and `why` ≤ 25 words each. `/retro` reads many of these in sequence; long notes hide the signal.
- Never append while no `.active` marker exists. If you genuinely need to log something post-Phase-6, surface it to the user instead.

## Anti-patterns

- ❌ Inventing ticket IDs because the user didn't provide any
- ❌ Reading `01-fetch.json` and re-doing triage yourself instead of invoking `test-triage`
- ❌ Posting to Linear before all units have been executed (or skipped intentionally)
- ❌ Adding back a "are you sure?" confirmation between Phase 3 and Phase 5. The user removed it on purpose. If you think a particular spec is too risky to auto-execute, that risk belongs in the spec's `[skip-on-this-pass]` scenarios or in `Open questions`, not in a global confirmation prompt.
