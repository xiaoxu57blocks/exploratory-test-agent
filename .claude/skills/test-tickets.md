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

After it returns, **run pre-flight check** before proceeding:

```bash
scripts/check-phase.py --run-id <run-id> --phase fetch
```

If it exits non-zero, stop and surface the error to the user — the fetcher claimed done but didn't write what it owes. If any tickets errored (in `errors[]`), tell the user and ask whether to continue with the rest.

### Phase 2 — Triage

Invoke the `test-triage` agent with the run-id.

After it returns:

```bash
scripts/check-phase.py --run-id <run-id> --phase triage
```

Stop on non-zero exit.

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

### Phase 2.5 — Data Planning

After triage finishes (and after any user-review pause is resolved), invoke the `test-data-planner` agent with the run-id. The planner reads `02-triage.json`, walks each unit's PR diffs, and decides per-unit whether to create a fresh case or reuse an existing one — and (for fresh cases) which fixture documents the case should contain. Output: `artifacts/<run-id>/02b-data-plan.json`.

After it returns:

```bash
scripts/check-phase.py --run-id <run-id> --phase data-plan
```

Stop on non-zero exit — a malformed data plan would mislead the strategist and executor.

**No user gate at this phase.** The plan is recorded and visible in `02b-data-plan.json` and again in the final `05-summary.md`. If the planner had to auto-add an entry to `fixtures/manifest.json` via Drive search, the planner notes it in `02b-data-plan.json`'s `manifest_changes[]` — surface the count to the user when announcing Phase 3 starts ("Data plan written. N units in M case-groups (P fresh / Q reuse). K manifest entries auto-added — review before next run.").

If the plan has any `case_decision: blocked_no_fixture` entries, **still proceed to strategy** — the strategist will write the spec, the executor will FAIL the affected scenarios with the planner's `fixture_gap` reason, and the human gets a clear actionable signal in the Linear comment instead of a silently-skipped unit.

### Phase 3 — Strategy

For each test unit that survived triage:

1. Announce: "Generating spec for unit-X covering SUP-NNN, SUP-MMM (env=<env>, role=<role>)"
2. Invoke the `test-strategist` agent with the run-id, unit_id, env, and role.
3. After it returns:
   ```bash
   scripts/check-phase.py --run-id <run-id> --phase spec --unit <unit_id>
   ```
   This validates both the markdown and the JSON sidecar exist and that the sidecar conforms to `schemas/run-spec.schema.json`. Stop on non-zero exit — the strategist's output is the executor's only input, so a malformed spec must not pass through.
4. Briefly show the user the generated spec's title, scenario count, and any open questions.

Run units **sequentially**, not in parallel — strategist has shared filesystem state (the artifacts dir).

### Phase 5 — Execute and Report (per unit)

Phase 5 is the only phase that does **not** delegate execution to a sub-agent. Drive Chrome from your own (main-session) context, following `.claude/agents/test-executor.md` as a runbook. See that file's "Why this is not a sub-agent" section — `mcp__chrome-devtools__*` tools are deferred and do not propagate to spawned sub-agents on the current Claude Code build, so any attempt to invoke `Agent({subagent_type: "test-executor", ...})` will produce a sub-agent that has only `[Read, Write, Bash]` and cannot drive a browser.

**Each unit is processed end-to-end before the next unit starts** — execute, validate, post Linear comments, then move on. This means the human watching Linear sees each ticket's result the moment its unit finishes, instead of waiting for all units to complete before any feedback appears.

For each confirmed unit:

#### Phase 5a — Execute

1. Announce: "Executing unit-X via Chrome DevTools MCP (in-context, following test-executor runbook)"
2. **Load Chrome DevTools tools into your context** by running the `ToolSearch` call documented at the top of `.claude/agents/test-executor.md` ("Loading Chrome DevTools tools"). Do this once per `/test-tickets` invocation; subsequent units in the same run reuse the loaded tools.
3. Read `.claude/agents/test-executor.md` and follow its workflow yourself: read the spec sidecar, log in, run the feature-flag pre-flight, do component-identity verification, run each scenario, write `trace.jsonl`/`result.json`/screenshots, and (only if all primary scenarios passed) generate `generated.spec.ts`. Treat every "you" in that document as referring to you, the orchestrator, in the current session.
4. After all scenarios for the unit have been executed and artifacts written, run:
   ```bash
   scripts/check-phase.py --run-id <run-id> --phase execute --unit <unit_id>
   ```
   This validates `result.json` and `trace.jsonl` against their schemas. The runbook tells you to self-validate before declaring done; this is defense in depth. If validation fails, fix the artifacts and re-run the check before continuing.

#### Phase 5b — Report (this unit only, immediately after execute)

5. Invoke the `linear-reporter` agent in **per-unit mode** with the run-id and `unit_id`. The reporter posts one Linear comment per ticket in this unit, attaches per-scenario screenshots, and appends a per-unit section to `05-summary.md`. The reporter prompt should be unambiguous: "Post results for run `<run-id>`, unit `<unit_id>` only — do not touch other units."

   If the reporter returns a non-success status (e.g. `result.json` validation failed late, Linear API error), surface it to the user but **do not abort the whole pipeline** — keep going to the next unit. Each unit's reporting is independent. The aggregate-mode reporter call at Phase 6 will surface any unit that didn't get its per-unit comment posted.

6. Show the user a one-line status: "Unit-X: PASS/FAIL/error — Linear comment posted on TICKET-N." Plus the path to `04-run-<unit_id>/result.json` and `generated.spec.ts` if produced.

Then move on to the next unit and repeat 5a + 5b.

Run units **sequentially**. Do not parallelize — they share a Chrome session, and per-unit reporting is part of the per-unit boundary.

**Why per-unit reporting?** A 5-unit batch reporting only at end-of-run gives the human nothing for ~30 minutes, then a flood. Per-unit reporting puts the first ticket's result in front of the human in ~5 minutes, so they can interrupt the run on a real product bug instead of waiting for everything to finish.

**Why not a sub-agent for execute?** See `.claude/agents/test-executor.md`. Short version: deferred MCP tool schemas are not propagated to sub-agents at spawn time, so the sub-agent ends up unable to call any `mcp__chrome-devtools__*` tool. This was reproduced on extension v2.1.133 / CLI 2.1.25 across multiple sessions; the design now reflects the actual loader behavior rather than the intended one. If a future Claude Code release fixes deferred-tool propagation, this skill can be reverted to invoke a sub-agent — verify with a probe spawn first.

### Phase 6 — Aggregate

By this point every unit has already had its Linear comment posted in Phase 5b. Phase 6 only writes the aggregate summary and cleans up the run's session state.

1. Invoke the `linear-reporter` agent in **aggregate mode** (no `unit_id` in the prompt). It rewrites `artifacts/<run-id>/05-summary.md` with the canonical aggregated structure: per-unit sections, skipped-ticket section, final tally, follow-ups. **No Linear writes happen in this mode** — Phase 5b already posted everything.

2. **Remove the active marker**: `rm artifacts/<run-id>/.active`. From this point on, further user prompts will not be appended to this run's `interventions.jsonl` — they belong to whatever conversation comes next, not to this test run.

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
