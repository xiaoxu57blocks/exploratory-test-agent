---
name: switch-account
description: Log out of the current Supio Portal account and log in as a different role (internal or external), then restore the active run's localStorage feature-flag overrides on the new session. Uses the avatar-menu Log out button — fast and reliable when driven directly. Usage `/switch-account --role internal|external [--env prod|stg]`.
---

# /switch-account

You drive Chrome (via the chrome-devtools MCP tools already loaded in this session) to switch the logged-in Portal account from one role to another with the minimum possible friction.

## Why this skill exists

Earlier runs spent 2-3 minutes per role-switch hunting through random approaches (deleting JS-readable cookies that turned out not to exist, navigating to a `/logout` route that bounced back, dispatching synthetic mouse events that React ignored). The actual avatar-menu Log out button works in ~3-5 seconds when you go straight to it. This skill encodes the direct path so callers never have to re-discover it.

It matters because:

- Several Linear ACs require a role switch to test (e.g. an internal-only button-hide gate). If the switch is expensive, runs are tempted to skip those ACs — exactly what the "never skip ACs" rule forbids.
- Mid-run role switches can happen multiple times in a single unit. Each bounce should cost seconds, not minutes.

## Why the cookie-delete fast-path doesn't work

The Portal session is keyed on a cookie named `id`, but inspection confirms two properties that block any JS-side delete:

- **HttpOnly = true** — JavaScript cannot read or write the cookie via `document.cookie`. The browser explicitly hides HttpOnly cookies from page scripts to prevent XSS theft.
- **Domain = `api.supio.com`** — the cookie is scoped to the API host, not `portal.supio.com`. Even if it weren't HttpOnly, page JS running on `portal.supio.com` cannot write to a cookie scoped to a different host.

Together these mean the only way to clear `id` is to ask the server to clear it, which is what the avatar-menu Log out button already does. If you ever see a future Portal release flip `id` to non-HttpOnly + same-origin, a JS-side fast-path becomes possible — update this skill at that point. Don't speculate-build it now.

## Args

- `--role <internal|external>` — required. The role to log in as.
- `--env <prod|stg>` — optional. Defaults to the `default_env` field in `.claude/test-env.local.json`.

## Inputs you read

- `.claude/test-env.local.json` — credentials for the target role+env. If creds are `null` for the requested combo, abort with a clear message.
- `localStorage.enabledFeatureFlags` and `localStorage.knownBackendFlags` on the current page — the run's flag overrides, snapshotted *before* logout so they survive the logout/login cycle.

## Workflow

1. **Resolve env + creds.** Read `.claude/test-env.local.json`. If `--env` was passed, use it; otherwise use `default_env`. Look up `environments[<env>].accounts[<role>]`. If `username` or `password` is `null`, abort with:
   ```
   Cannot switch to <role> on <env>: credentials are null in test-env.local.json. Either provision the account or pick a different env.
   ```

2. **Snapshot the run's localStorage flag overrides.** Run via `evaluate_script`:
   ```js
   () => ({
     enabledFeatureFlags: localStorage.getItem('enabledFeatureFlags'),
     knownBackendFlags: localStorage.getItem('knownBackendFlags'),
   })
   ```
   Hold the result in agent-local memory as `ff_snapshot`. Both keys can be null — that's fine; they just won't be restored after login.

3. **Click the avatar to open the user menu.** The avatar is a `span.ant-avatar` element in the top-right header whose `textContent` is the user's initials (e.g. `ST` for the external test account, `OA` for `OPSadmin@test.com`). Avatars also appear in the case list (one per case, much smaller); the *header* avatar is the one in the page banner. Use `evaluate_script` to find and click it directly rather than via snapshot uid — the snapshot can be huge if the Sessions sidebar is open and uids change between snapshots:
   ```js
   () => {
     const avatars = Array.from(document.querySelectorAll('span.ant-avatar'));
     // The header avatar is the first one inside <header> / banner / role=banner ancestry,
     // OR fall back to the first one near the top of the page (smallest y-coord).
     const header = avatars.find(a => a.closest('header, [role="banner"]')) || avatars.sort((a,b)=>a.getBoundingClientRect().y - b.getBoundingClientRect().y)[0];
     if (!header) return { error: 'no avatar found' };
     header.click();
     return { clicked: true, initials: (header.textContent||'').trim() };
   }
   ```

4. **Click the "Log out" button in the menu.** After step 3, an antd dropdown / popover appears with menu items. Find the one whose visible text matches `/log\s*out|sign\s*out/i` and click it:
   ```js
   () => {
     const btn = Array.from(document.querySelectorAll('a, button, [role="menuitem"]'))
       .find(e => /log\s*out|sign\s*out/i.test(e.textContent || ''));
     if (!btn) return { error: 'no log-out menuitem found; menu may not have opened' };
     btn.click();
     return { clicked: true };
   }
   ```
   If this returns `error: 'no log-out menuitem found'`, retry step 3 once with a small wait — the menu may not have rendered yet. If it still fails, abort with a screenshot for human review.

5. **Wait for the login page.**
   ```
   wait_for ["Log in", "Email", "Password"] timeout=20000
   ```
   The Portal redirects to `/login` once the server has cleared the `id` cookie. If this times out, surface the current URL and abort — something else is wrong (network failure, account session not actually cleared).

6. **Fill the login form and submit.**
   - `take_snapshot` to get the Email textbox uid, Password textbox uid, and Log in button uid. Login pages are tiny so the snapshot is cheap; do it here, not in step 3.
   - `fill_form` with `[{uid: <email-uid>, value: <username>}, {uid: <password-uid>, value: <password>}]`.
   - `click` the Log in button.

7. **Wait for the post-login landing page.** Different roles see different landings:
   - external attorney with `feature-case-agent` ON → `/` (case-agent landing with "Good morning, ..." greeting and Sessions sidebar).
   - external attorney with `feature-case-agent` OFF → `/timeline` (cases list with "Active"/"Archived" tabs).
   - internal Supio user → `/` with extra menu items (Annotate, Timeline, Cases, Chat) visible.

   ```
   wait_for ["Sessions", "Cases", "Active", "Click on a menu", "Good morning"] timeout=30000
   ```
   Any of those is sufficient evidence we're past login.

8. **Restore the run's localStorage flag overrides.** Run via `evaluate_script` with `ff_snapshot` as the function arg:
   ```js
   (snapshot) => {
     if (snapshot.enabledFeatureFlags) localStorage.setItem('enabledFeatureFlags', snapshot.enabledFeatureFlags);
     if (snapshot.knownBackendFlags) localStorage.setItem('knownBackendFlags', snapshot.knownBackendFlags);
     return { applied: !!snapshot.enabledFeatureFlags, ff: localStorage.getItem('enabledFeatureFlags') };
   }
   ```

9. **Reload once more.** Without this reload, the React store reads the *new* account's empty/default flag set on first paint and gates UI accordingly. The reload picks up the localStorage overrides we just restored.
   ```
   navigate_page type=reload timeout=30000
   wait_for [<same landing-page texts as step 7>] timeout=30000
   ```

10. **Return a structured result.**
    ```json
    {
      "ok": true,
      "role": "<internal|external>",
      "env": "<prod|stg>",
      "account_email": "<email>",
      "ff_restored": true,
      "approx_seconds": 8
    }
    ```
    `ff_restored: false` if step 2's snapshot was empty (no overrides to restore — not an error).

## Hard rules

- **Never echo passwords.** The password is read into agent-local memory and used only in step 6's `fill_form`. It must not appear in any trace, screenshot, finding, or chat output.
- **Never call `localStorage.clear()` or `sessionStorage.clear()`.** Those would erase the flag snapshot you just took. The avatar-menu Log out preserves localStorage — that's why this skill works.
- **Snapshot localStorage BEFORE the menu click, not after.** A few rare bug paths in the Portal may clear localStorage on logout. Capturing first guarantees we have the values to restore.
- **The skill assumes chrome-devtools MCP tools are already loaded in the calling session.** It does not call `ToolSearch` itself — that's the orchestrator's responsibility (per Phase 5a of `/test-tickets`). If the tools aren't loaded, the first `evaluate_script` call will fail with "tool not available" and the skill must surface that as the error.
- **Do not navigate to `/logout` as a route.** Empirically the Portal redirects `/logout` back to `/` with the session intact, so it doesn't actually log you out. The avatar menu's Log out button is the only path that fires the actual logout request to `api.supio.com`.

## When NOT to use this skill

- **Cross-env switching** (prod → stg or vice versa). This skill switches *role* within an env, not env. Cross-env requires re-pointing at the other host's `/login` page and is out of scope here.
- **Logging in fresh from a no-session state.** If the browser has no `id` cookie at start, the avatar won't be there to click — you're already on `/login`. In that case skip to step 6 directly using the calling agent's normal login flow; this skill isn't designed for that path.
- **Switching between two external accounts.** This skill is keyed on `internal` vs `external` per `test-env.local.json`. If you need to switch between two different external accounts, extend the schema to support named accounts within a role and update this skill.

## Anti-patterns

- ❌ **Trying to delete the `id` cookie via `document.cookie = 'id=; ...'`.** It's HttpOnly + scoped to `api.supio.com`; JS on `portal.supio.com` cannot touch it. Don't waste time on this — it's why this skill exists.
- ❌ **Hunting through `take_snapshot` to find the avatar's uid.** When the Sessions sidebar is open the snapshot is enormous (>100 KB) and uids change between snapshots. Use `evaluate_script` with a CSS-selector probe instead (step 3).
- ❌ **Falling back to "navigate to /logout".** That route is a no-op — it bounces back to `/` without clearing the session. Don't even try it.
- ❌ **Skipping the localStorage restore "because the new account has its own flags."** The restore preserves *runtime test overrides*, not the user's persistent preferences. A spec that requires `feature-X=on` needs that override on every account it switches to mid-run; otherwise the post-switch scenarios silently run against the pre-feature path.
- ❌ **Not reloading after step 8.** The React store reads localStorage on first paint only. Setting `enabledFeatureFlags` after the page is rendered does nothing until the next reload.
