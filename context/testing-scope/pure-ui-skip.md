# Rule: pure-ui-skip

## When this rule applies

A ticket qualifies as **pure-UI** when ALL of the following hold:

- The ticket title or description signals visual/layout intent only — e.g. "adjust margin", "fix spacing", "update color", "align icon", "polish", "tweak padding", "pixel-perfect", "redesign button style", "update typography", "fix CSS", "adjust layout", "responsive fix".
- The linked PR diff contains **only** changes in CSS/SCSS/styled-components/Tailwind values, inline style props (`margin`, `padding`, `top`, `left`, `width`, `height`, `color`, `font-size`, `gap`, `border-radius`, etc.), or purely presentational attribute changes (`className`, `style`). No new components, no new event handlers, no store mutations, no API calls, no routing changes.
- The ticket has **no** acceptance criteria that describe user-observable behavior (state changes, navigation, data shown/hidden, permissions).

If even one of these does **not** hold, do not apply this rule — use `ui-logic-mixed-scope` instead.

## What it controls

`test-triage` must skip the ticket and record it in the `skipped` array with:

```json
{
  "rule": "deterministic",
  "confidence": "high",
  "reason": "pure-UI change (layout/spacing/color only) — no behavior to assert"
}
```

## Linear comment requirement

Even though the ticket is skipped, `linear-reporter` MUST post a comment on the ticket that:

1. States it was evaluated and skipped.
2. Explains the reason: pure visual change with no observable business behavior.
3. Advises: visual regressions should be covered by screenshot diffing / Chromatic / Storybook, not E2E tests.

Template:

> **Test agent — skipped (pure UI change)**
>
> This ticket was evaluated by the test agent and skipped from E2E test coverage.
>
> **Reason:** The PR diff contains only visual/layout changes (CSS values, spacing, color, typography). There is no user-observable behavioral change (no state change, no navigation, no data visibility rule, no permission gate) that an E2E test can assert.
>
> **Recommendation:** Visual regressions from changes like this are best caught by screenshot-diffing tools (Chromatic, Percy, or Playwright `toHaveScreenshot`) rather than interaction tests.
>
> _Run: `<run-id>` · Evaluated by test-triage_

## Known interactions

- This rule takes precedence over the general "LLM judgment" layer in `test-triage` when the signal is unambiguous.
- When confidence is medium (e.g. "update button style" but the PR diff is not yet readable), fall through to LLM judgment with `confidence: "medium"` and add to `needs_user_review`.
