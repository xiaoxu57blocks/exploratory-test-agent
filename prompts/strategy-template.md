# Requirement Spec Template

This is the canonical format for a Requirement Spec produced by `test-strategist`. The `test-executor` agent consumes this spec to drive Chrome via Chrome DevTools MCP.

Fill in every section. If a section has no content, write `_None._` — do not omit the heading.

---

# <Title — concise, names the feature>

## Source tickets

- [LIN-1234](https://linear.app/...) — <ticket title>
- [LIN-1235](https://linear.app/...) — <ticket title>

## Scope summary

<2-4 sentences. What is the user-facing change? Who uses it? What problem does it solve?>

## Preconditions

- **Environment**: `prod` | `stg` (the executor reads URL from `.claude/test-env.local.json`)
- **User role**: `external` | `internal` (the executor reads credentials from `.claude/test-env.local.json` for this role)
- **Feature flags** _(one bullet per flag — read by `test-executor`'s pre-flight; keep the format strict)_:
  - `feature-<name>` — `enable_required` (gates: <what it gates per the diff>)
  - `feature-<other>` — `must_be_off` (kill-switch / cleanup gate)
  - If unsure: list the flag in **Open questions** instead of guessing. Do not write `<unknown>` here — the pre-flight cannot act on unknowns.
- **Data setup**: <case state, files uploaded, role assignments — anything the test must seed before the user actions begin>
- **External systems**: <if connectors required: SmartAdvocate, OneDrive, Litify, etc.>

## Test scenarios

Scenarios are written for an LLM-driven executor — describe **observable user actions and observable outcomes**. Do not write selectors, code, or DOM details. The executor will navigate, look, and decide which element matches based on the description.

### 1. [primary] <Scenario name> [LIN-1234]

**Given** <starting state — what page is open, what data exists>
**When** <user action — described in product terms: "user clicks New Case", "user fills in Case Name with 'X'">
**Then** <observable outcome — what the user should see: "the page navigates to the case overview", "the Case Stage selector appears with 5 options">

### 2. [primary] <Scenario name> [LIN-1235]

**Given** ...
**When** ...
**Then** ...

### 3. [edge] <Edge case scenario> [LIN-1234]

**Given** ...
**When** ...
**Then** ...

### 4. [skip-on-this-pass] <Out-of-scope scenario>

**Reason**: <why this is deferred>

## Out of scope

- <thing 1 this spec deliberately does NOT test>
- <thing 2>

## Open questions

- <question 1 — what info is missing from source tickets>
- <question 2>

---

## Filling guide

### Scenario tags
- `[primary]` — must pass for the ticket to be considered tested. Fail blocks the report.
- `[edge]` — boundary, error, permission cases. Fail is logged but not blocking.
- `[skip-on-this-pass]` — known to be out of scope or blocked. Documented for completeness.

### Each scenario must be
- **Atomic** — one user-observable behavior
- **Traceable** — `[LIN-XXXX]` reference at minimum
- **Concrete enough that an LLM can drive the browser from it**, but free of selectors / DOM / framework details

### Writing for the LLM-driven executor

✅ Do:
- "User clicks the **New Case** button" (describes the affordance the user sees)
- "The Case Stage selector appears with options: Intake, Treatment, Demand & Negotiation, Settlement, Litigation"
- "URL contains `/cases/<id>/overview`" (asserting on URL is fine — it's user-observable)

❌ Don't:
- "Click `button[data-testid='new-case-btn']`" (selectors are the executor's job)
- "Wait 2000ms then assert..." (the executor handles timing)
- "Page should match this DOM tree..." (write what the user perceives, not the implementation)

### Open questions section
This is where you put uncertainty. The orchestrator will pause and ask the user. Use it for:
- Missing acceptance criteria
- Ambiguous expected behavior
- A feature flag the linked PRs reference but whose effect on the surface under test is unclear
- Role assumption that needs confirmation

Do NOT use it for things you should have figured out (e.g. "what test environment should we use" — that's a precondition).

### Feature flags — where they come from
The strategist reads each linked GitHub PR via the Linear MCP (`mcp__linear__get_diff` / `mcp__linear__get_diff_threads`) and greps the diff for `feature-*`, `feature_*`, `isFeatureFlagEnabled("…")`, `enabledFeatureFlags`. Every flag found in the diff that gates a code path on the test surface goes into Preconditions. Flags merely *referenced* by adjacent code (e.g. an unrelated kill-switch) belong in Open questions, not Preconditions.
