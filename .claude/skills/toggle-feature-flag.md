---
name: toggle-feature-flag
description: Enable or disable a Supio Portal feature flag for the current browser session by writing to localStorage.enabledFeatureFlags, then reloading the page so the override takes effect. Usage `/toggle-feature-flag --flag <name> on|off`. Works for any flag whose UI gating is controlled by the localStorage key — reports clearly when a flag appears to be backend-only.
---

# /toggle-feature-flag

You drive Chrome (via the chrome-devtools MCP tools already loaded in this session) to turn a Portal feature flag on or off for the current browser session.

## Why this skill exists

The Feature flag pre-flight block in the test-executor runbook repeats the same 20-30 line GraphQL + localStorage + reload template for every flag, on every run. Extracting it here saves context tokens and keeps the executor runbook readable. Any scenario that needs a flag state change calls this skill; the runbook no longer needs to inline the implementation.

## Args

- `--flag <name>` — required. The flag string as it appears in `localStorage.enabledFeatureFlags`, e.g. `feature-ai-artifact-first`.
- `on` / `off` — required. Desired end state.

Example:

```
/toggle-feature-flag --flag feature-ai-artifact-first on
/toggle-feature-flag --flag feature-some-other-flag off
```

## Pre-flight

1. A browser page must already be open and logged in to the Portal (`portal.supio.com` or `stg-portal.supio.com`). If not, fail immediately with `no logged-in Portal page found`.
2. `mcp__chrome-devtools__list_pages` to confirm the selected page URL starts with the Portal host.

## Workflow

### Step 1 — Check backend entitlement

```js
async () => {
  const r = await fetch('https://api.supio.com/api/v1/base', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: '{ me { id email enabled_feature_flags } }'
    })
  });
  const j = await r.json();
  return {
    email: j.data?.me?.email,
    flags: j.data?.me?.enabled_feature_flags ?? []
  };
}
```

Record `backend_enabled: true|false` for the requested flag.

- If `on` was requested but `backend_enabled=false`: the account is not entitled. The localStorage override has **no effect** for flags the backend has not granted — the React store's `useFeatureFlag` hook checks both. Abort with:

  ```
  toggle-feature-flag: flag '<name>' is not enabled on the backend for <email>.
  Cannot force-on via localStorage — the account must be granted this flag server-side first.
  If this is unexpected, check the test account's flag entitlements in the admin panel.
  ```

  Do NOT proceed to localStorage. This is `backend-only, cannot override`.

- If `off` was requested: backend state is informational only. localStorage removal is sufficient to suppress the flag in the UI regardless of backend state.

### Step 2 — Write localStorage

```js
() => {
  const raw = localStorage.getItem('enabledFeatureFlags') || '';
  const current = raw.split(',').filter(Boolean);
  const flag = '<name>'; // the --flag argument

  let next;
  if ('<on|off>' === 'on') {
    next = Array.from(new Set([...current, flag]));
  } else {
    next = current.filter(f => f !== flag);
  }

  localStorage.setItem('enabledFeatureFlags', next.join(','));
  return {
    before: current,
    after: next,
    stored: localStorage.getItem('enabledFeatureFlags')
  };
}
```

### Step 3 — Reload

```js
// navigate_page with type=reload
```

Wait for the page to finish loading (`wait_for` on text that confirms the page is interactive — e.g. the logged-in user's display name or a known nav element).

### Step 4 — Verify

Re-read `localStorage.getItem('enabledFeatureFlags')` after reload and confirm the flag is present (on) or absent (off).

Return a one-line confirmation to the caller:

```
toggle-feature-flag: 'feature-ai-artifact-first' → on  (backend: enabled, localStorage: applied, page reloaded)
toggle-feature-flag: 'feature-some-flag' → off  (backend: enabled, localStorage: removed, page reloaded)
```

## Trace entry

Emit one trace entry to `trace.jsonl` after success:

```json
{
  "ts": "<ISO-8601>",
  "event": "feature_flag_preflight",
  "flag": "<name>",
  "desired": "on|off",
  "backend_enabled": true,
  "localStorage_before": ["..."],
  "localStorage_after": ["..."],
  "outcome": "on|off"
}
```

## Error states

| Situation | Action |
|---|---|
| No Portal page open | Abort: `no logged-in Portal page found` |
| GraphQL unreachable (network error) | Fall back to dev-panel toggle (avatar → coffee-cup icon → flag search → toggle). Trace with `method: "dev_panel_toggle"`. Use only when GraphQL fails. |
| Flag not in backend + `on` requested | Abort with backend-only message (see Step 1). Do not touch localStorage. |
| Flag already in desired state | Skip Steps 2–3 (no-op). Return `toggle-feature-flag: '<name>' already <on|off>, no change.` |

## What this skill does NOT do

- Does not change the backend's `enabled_feature_flags` for the account — only the in-browser localStorage override.
- Does not remember flag state across sessions. Each new browser session starts with whatever `localStorage` the Portal sets on login.
- Does not validate that the flag name is spelled correctly — if you pass a typo, Step 4 will confirm it was written, but the UI won't gate on it. The caller is responsible for the exact flag string.
