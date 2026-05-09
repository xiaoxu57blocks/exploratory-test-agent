---
name: test-executor
mode: in-context-runbook
description: Runbook the ORCHESTRATOR follows in the main session to execute a Requirement Spec end-to-end against a real browser using Chrome DevTools MCP. NOT a sub-agent. Drives Chrome step-by-step, captures screenshots and a trace, evaluates each scenario's Then-clauses, and produces a generated.spec.ts (Playwright) reflecting the path that worked.
---

# test-executor (in-context runbook)

The orchestrator (the main `/test-tickets` session) reads this file and follows it. **Do not** invoke this via `Agent({subagent_type: "test-executor"})` — sub-agents don't receive deferred MCP tool schemas, so a spawned executor can't actually call any `mcp__chrome-devtools__*` tool. Driving Chrome from the main session is the only configuration that works on Claude Code (extension v2.1.133, CLI 2.1.25). If a future release fixes deferred-tool propagation, verify with a probe spawn before reverting.

**First step in Phase 5**: load the chrome-devtools tools into context.
```
ToolSearch({query: "select:mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__new_page,mcp__chrome-devtools__list_pages,mcp__chrome-devtools__select_page,mcp__chrome-devtools__resize_page,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__take_snapshot,mcp__chrome-devtools__click,mcp__chrome-devtools__fill,mcp__chrome-devtools__fill_form,mcp__chrome-devtools__evaluate_script,mcp__chrome-devtools__wait_for,mcp__chrome-devtools__press_key,mcp__chrome-devtools__type_text,mcp__chrome-devtools__list_console_messages,mcp__chrome-devtools__list_network_requests,mcp__chrome-devtools__upload_file,mcp__chrome-devtools__handle_dialog,mcp__chrome-devtools__hover", max_results: 25})
```
Add more via subsequent `ToolSearch` if you need them (`get_console_message`, `get_network_request`, etc.).

## Inputs / Outputs

**Inputs**
- `artifacts/<run-id>/03-spec-<unit_id>.json` — the spec sidecar (contract; do not parse the .md sibling).
- `.claude/test-env.local.json` — URLs + creds per env per role.
- `artifacts/<run-id>/02b-data-plan.json` (optional) — the planner's case decision for this unit.

**Outputs under `artifacts/<run-id>/04-run-<unit_id>/`**
- `trace.jsonl` — one JSON object per step. Schema: `schemas/run-trace.schema.json`. The schema field is `event`, never `t`.
- `screenshots/` — PNGs at named checkpoints + every failure.
- `result.json` — per-scenario verdict. Schema: `schemas/run-result.schema.json`.
- `generated.spec.ts` — Playwright translation of the **successful** trace. **Only** create this when all `[primary]` scenarios passed.

## Hard rules

### Credentials

- Read creds from `.claude/test-env.local.json` once at run start; hold in agent-local memory; use only for login.
- **Never** write the password into trace, screenshots (mask password fields before screenshotting), result.json, generated.spec.ts, or chat. The generated.spec.ts must reference creds via `process.env.SUPIO_USERNAME` / `process.env.SUPIO_PASSWORD`.
- If the requested env+role has `null` creds, abort with a clear message — do not silently fall back to the other role.

### Mid-run role switching

When a scenario's `user_role` differs from the unit's default:
1. Group same-role scenarios first; run role-switching scenarios in a tail group.
2. Invoke the **`/switch-account` skill** with `--role <target>`. Don't roll your own logout/login flow — earlier runs wasted 2-3 minutes per switch; the skill encodes the working path. See `.claude/skills/switch-account.md`.
3. After the role-switching scenario, invoke `/switch-account --role <original>` to restore the unit's default.
4. If creds are `null` for the target role, mark the scenario FAIL with `fail_reason: "<role> credentials not provisioned for env=<env>; AC requires <role> role"`. **Do not** mark `skipped_per_spec` — a missing role is a real test gap.
5. Record each switch as a `login_as` trace entry with the new account's email (returned by the skill).

### Fresh AI session by default

For chat / AI-session UX (case-agent, mailroom-chat, drafting-agent), **create a new session at scenario start** unless the spec's `data_setup` names a specific existing session as a fixture. Reusing the top-of-sidebar session is forbidden — non-reproducible, leaks state across runs, may have been created on the old code. Send a prompt known to produce the needed citations/state, wait for the reply, then exercise the scenario.

### Browser driving rules

**Page load waiting (slow target site).** Default `navigate_page` timeout (10s) often fires before the page is ready, returning an error while loading continues. Treat every navigation/click-that-changes-page as: (1) trigger, (2) confirm load — `wait_for` on text you expect on the post-load page (e.g. `["Log in"]` for login, the user's display name for a logged-in dashboard), or fall back to `evaluate_script` returning `{readyState, url, title}`. Pass explicit `timeout: 30000` on slow pages. **A `navigate_page` timeout is not a failure** — check `list_pages`/`evaluate_script` first; only treat it as failure if `wait_for` *also* times out. Never screenshot or assert before confirming load — blank-background screenshots are always a workflow bug.

**Reloads are evidence-destroying.** Reloading erases live-update bugs: the timeline that didn't push events when extraction completed, the file-status badge that didn't advance, the Case Activity card that didn't refresh. If you reload "to verify the next step", you can't tell whether data appeared because of the reload or because the app updated live. Rules:
1. **Don't reload** unless (a) the spec or PR explicitly names a reload as a When step (testing localStorage/cookie/DB persistence specifically), or (b) the page is in a wedged error state.
2. **Before any spec-required reload, run a live-update sanity sweep**: `evaluate_script` snapshot the live-data widget's count/state and compare to what the network response said it should be. Mismatches go in `result.json.live_update_findings[]` as `[Warning]` items, not as scenario PASS/FAIL.
3. **Prefer in-page actions over reloads**: tab-switch, scroll-to-fetch, `evaluate_script` polling for ~10s.
4. **Order matters**: when a spec needs both observation and reload, observe *first*, then reload.

(Original example: SUP-7623 — close-persists-across-reload PASSed, but the executor missed that timeline events didn't auto-populate as extraction completed; only after the close-and-reload in scenario 4 did events appear. That's a finding worth reporting; a premature reload would have hidden it.)

**Server-side processing waits (Supio case parsing).** Uploading files enqueues a parsing job that takes 3-15 minutes. The Timeline tab does not show a clear "still processing" indicator and lags Overview by a polling cycle. The canonical signal is on **Overview tab → Case Activity card (top-right)**:
- Processing: `IN PROGRESS · Extracting timeline data · Nm`
- Done: `NEEDS ATTENTION · N new events added to Timeline · from M files`

Procedure: navigate `/timeline/<case_id>?t=overview`, `wait_for(["IN PROGRESS","NEEDS ATTENTION","events added"], timeout=15000)`. If `IN PROGRESS`, yield via `ScheduleWakeup` for 90-120s and re-poll. Cap total wait at 20min; if still `IN PROGRESS`, abort with "parsing exceeded ceiling". Never poll the Timeline tab to detect parse completion. Never write a hardcoded `sleep 600s`.

**Fixture file paths.** chrome-devtools MCP only reads files inside its workspace roots. Anything under `~/Downloads`, `/tmp`, `~/Desktop`, etc. will be refused with `Access denied: path ... is not within any of the workspace roots`. Every fixture the executor uploads must live under `artifacts/<run-id>/` — copy in from elsewhere first if needed.

**Browser lifecycle.** Prefer a clean profile per run. After each scenario, reset to a clean state (navigate to env base URL or close+reopen the page) — scenarios must not leak state into each other. On unrecoverable error: final screenshot, write what you know to `result.json`, exit. No silent retry-forever.

### Feature flag pre-flight (run BEFORE any state-creating action)

Supio has a runtime flag-sync gap: backend `me.enabled_feature_flags` may include a flag, but the React store only honors it after a local override appears in `localStorage.enabledFeatureFlags`. Skipping pre-flight makes the UI render the *pre-feature* path and produces false-negative scenario failures.

For every flag in `Preconditions → Feature flags`:
1. **Confirm backend** — POST `https://api.supio.com/api/v1/base` with `query me { me { id email enabled_feature_flags } }` via `evaluate_script` + `fetch(..., {credentials:'include'})`. If `enable_required` and missing from backend, abort — the test account isn't entitled.
2. **Force the runtime override**:
   ```js
   () => {
     const have = (localStorage.getItem('enabledFeatureFlags') || '').split(',').filter(Boolean);
     const need = ['feature-foo']; // from spec
     localStorage.setItem('enabledFeatureFlags', Array.from(new Set([...have, ...need])).join(','));
     return localStorage.getItem('enabledFeatureFlags');
   }
   ```
   For `must_be_off`: remove the flag from the same string.
3. **Reload** with `navigate_page({type:"reload"})` and re-confirm load. The override is read on first paint; without a reload, gated UI sections won't appear.
4. **Trace entry per flag**: `{"event":"feature_flag_preflight","flag":"...","backend_enabled":true,"runtime_override":"applied|already_present","outcome":"on"}`.

Fallback when GraphQL is unreachable: avatar → coffee-cup icon (`rest`) dev panel, search the flag, toggle on. Trace it with `method: "dev_panel_toggle"`. Use only when GraphQL fails — localStorage is deterministic and screenshot-able.

**Pre-flight runs before *every* state-creating action**, not just scenarios. If `data_setup` creates a case/session/workspace via a feature-gated flow, the flag must be ON before that creation — backends commonly bind pipelines/features at create-time, and toggling after the object exists doesn't retroactively switch the pipeline. (Observed: a case created with `feature-ai-artifact-first` OFF was permanently bound to the legacy pipeline; only a re-created case under flag-ON saw the new UI.)

### Component identity verification (before the FIRST scenario)

The spec names an exact component identity (`data-testid`, accessible role+name, or unique class chain) taken from the PR diff. Before any scenario, prove that exact component is reachable. If you can't, *don't run scenarios yet* — verdicts will be meaningless.

Procedure:
1. Re-read the spec's Preconditions + first scenario's Given. Note the exact selector.
2. Navigate to the Given URL; wait for load.
3. `evaluate_script` to count nodes matching the selector. **Hold to the exact selector** — not a textual match like "popover whose header says Timeline Complete". Identical-looking siblings are common (LedgerFilePanel and TimelineGenerationPanel both can show "Timeline" in the right-bottom slot).
4. Three outcomes:
   - **Match ≥1**: proceed to the scenario loop.
   - **Zero, but spec says it should be visible**: NOT a scenario FAIL. Either you picked the wrong case (legacy vs AI-first) or a visibility gate is closed (`wasEverProcessing=false` etc.). Stop, reconcile (different case, construct missing state, or Open-questions note), resume only after match.
   - **Zero, and spec asserts hidden**: legitimate observation. Still verify the Given holds (so absence is *because* of the gate, not because the component was never in the tree).
5. Record one `component_identity_verified` trace entry: case id, selector, hit count, outcome.

(Why this matters: SUP-7623 didn't pin a `data-testid`, the executor saw a popover in the right region with "Timeline Complete" in it, ran four scenarios against `data-testid="snapshot-window"` instead of the actual `timeline-generation-panel`, reported three FAILs that were spec gaps. Pin the identity, then verify it lands.)

### Case fitness check (run alongside identity verification)

Many specs target a specific kind of case (AI-first vs legacy, MVA vs other, fresh vs ledger-enabled). Cheap signals:
- **AI-first vs legacy**: AI-first cases mount components from `src/packages/ai-artifact-first/...`. Presence of `data-testid="timeline-generation-panel"` *anywhere* on the timeline tab — even hidden — is a positive signal. Total absence after 5s suggests legacy.
- **Case state**: if spec says "in `extracting`", check the network log for `ai-first-timeline-generation-status` with that status. Don't infer from header text — header copy lags by a polling cycle.
- **Per-user gates**: if spec mentions `useEducationDismissal`, check `/api/v1/user-education-dismissals/<key>/dismissed`.

Wrong-kind case is the highest-cost bug: it produces a FAIL report that looks plausible but is meaningless. When in doubt, create a fresh case via `/create-case` rather than reuse an unfamiliar one.

### Scenario execution

For each scenario in spec order:
1. Set up the **Given** state (often: log in, navigate). Reuse auth across scenarios if safe.
2. Perform the **When** actions; trace each with before+after screenshots if the action mutates the page.
3. Evaluate each **Then** — one `assert` entry per Then, `outcome: pass|fail`. **Do not collapse multiple Thens into one assert.**
4. If any `[primary]` Then fails: mark scenario failed, continue to the next scenario. Do not abort the whole run on a single primary failure.
5. Edge scenarios that fail are recorded but do not block report.

### Screenshot evidence — required for every active scenario, PASS or FAIL

Each scenario in `result.json` must include a `screenshot` (relative path under `04-run-<unit_id>/`). Three FAIL flavors:
- **Spec FAIL** (UI did the wrong thing): screenshot the post-action frame showing the wrong state.
- **Blocked-no-test-data FAIL**: screenshot the surface in a state that *proves* data is missing — the file list with the highest-event-count file visible (so reader sees "max=7, threshold needed >10"), the citation footer showing only Timeline-event entries (so reader sees "no ConversationFile here"). The picture must make the blocker self-evident.
- **Unreachable FAIL** (precondition can't be constructed): if there's nothing visible to photograph, omit the screenshot AND state in `fail_reason` why no frame exists ("requires internal role; external user never sees this surface"). Reporter renders the FAIL caption text-only.

When in doubt, take the screenshot. A picture proves the run happened; missing pictures invite the reader to assume the agent skipped the work.

### Generated Playwright translation

Run **only** if all `[primary]` scenarios passed. Translate `trace.jsonl` to a single `generated.spec.ts`:
- One `test()` per scenario.
- Use Playwright `getByRole`, `getByText`, `getByLabel` — prefer these over CSS selectors. Use the human descriptions stored in trace as the basis for locators.
- Read URL/creds from environment variables, not literals.
- Top-of-file comment: `// Generated from <run-id>/<unit-id> on <date>. Do not edit by hand — re-run the executor.`
- Add `test.describe.configure({ retries: 0 })` and a 30s default timeout — this is a recording, not a flaky-tolerant suite.

Translate, don't invent. No branches, retries, or assertions that weren't observed.

## Workflow

1. Read `artifacts/<run-id>/03-spec-<unit_id>.json` (the contract). Markdown sibling is human-only.
2. Verify env + role from sidecar `preconditions`. Load creds. Abort early on missing config.
3. Initialize Chrome DevTools MCP. Navigate to env base URL.
4. Log in once with the role from preconditions. `login_as` trace entry.
5. **Feature flag pre-flight** for every flag in `preconditions.feature_flags`. Abort if any `enable_required` flag is missing from backend.
6. **Resolve the case per the data plan.** If `02b-data-plan.json` exists, find the `case_groups[]` entry containing your `unit_id`:
   - Sibling already created the case this run? Read `case-group-<id>/case_id.txt` and **reuse** (trace `{"event":"case_reuse","case_id":"<N>"}`).
   - `case_decision: create_fresh`? Call `/create-case` skill with the plan's `case_kind` and each fixture in `fixtures_needed` via `--add <name>`. Write the new case-id to `case-group-<id>/case_id.txt`. Trace `{"event":"case_create",...}`.
   - `case_decision: reuse_existing`? Use `case_id` from the plan. Write to `case_id.txt` for symmetry. Trace `{"event":"case_resolve","source":"data-plan-reuse"}`.
   - `case_decision: blocked_no_fixture`? Write `result.json` with every active scenario `❌` and `fail_reason` from the plan's `fixture_gap`. Skip the scenario loop.
   - **Never override the plan unilaterally.** If you think the plan is wrong, surface it in `result.json.live_update_findings[]`; don't silently switch cases.
   - **Plan absent** (older path): fall back to reading `preconditions.data_setup` as before. Log a `live_update_findings` note that no plan existed.
7. **Component identity verification** + **Case fitness check** before any scenario.
8. For each scenario in `sidecar.scenarios` (array order), execute and evaluate per the rules. Append every step to `trace.jsonl`. Capture per-scenario screenshots per the Screenshot evidence rule.
9. Write `result.json` per schema. Required: `run_id`, `unit_id`, `tickets`, `env`, `user_role`, `verdict`, `passed_primary`, `scenarios[]`. FAIL scenarios need a `fail_reason`. Live-update anomalies go in `live_update_findings[]`.
10. **Self-validate before returning**:
    ```bash
    scripts/validate-artifact.py --kind result --path artifacts/<run-id>/04-run-<unit_id>/result.json
    scripts/validate-artifact.py --kind trace  --path artifacts/<run-id>/04-run-<unit_id>/trace.jsonl
    ```
    Don't return success while either is invalid — the reporter refuses to read invalid artifacts.
11. If `passed_primary`: generate `generated.spec.ts` from the trace.
12. Return: total scenarios, pass/fail breakdown, whether `generated.spec.ts` was created, run-dir path, "result+trace validated".

## Anti-patterns

- ❌ Inventing assertions not in the spec ("page renders without errors") — only assert what Then clauses say.
- ❌ Hardcoding waits (`sleep 2s`). Use `wait_for` / `evaluate_script` polling.
- ❌ Screenshot or assert before confirming page load. Blank-background screenshots mean the trace is lying.
- ❌ Catching failures and silently retrying. Every failure must be in the trace.
- ❌ Writing `generated.spec.ts` when primaries failed — a broken recording is worse than no recording.
- ❌ Leaking secrets. If unsure, treat as sensitive.
- ❌ Treating the first popover/widget in the right region as the SUT. Pin the component identity from the diff and verify it lands; don't settle for a similar-looking sibling. (See Component identity verification.)
- ❌ Calling a scenario FAIL when the Given-state can't be constructed. Stop, find or create a fitting case, then run. A wrong-case FAIL is louder than a real bug and harder to retract.
- ❌ Reloading "to make the next step easier". Reload erases live-update bugs. (See Reloads are evidence-destroying.)
