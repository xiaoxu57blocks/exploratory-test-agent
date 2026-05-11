# Rule: ui-logic-mixed-scope

## When this rule applies

A ticket is **mixed** when the PR diff (or ticket description) contains **both**:

- Business logic changes — new/changed behavior: conditional rendering of meaningful content, state transitions, API calls, routing, permissions, feature flag gates, data transformations, validation.
- Pure UI tweaks — visual-only changes alongside the logic: adjusting `margin`/`padding`/`top`/`color`/`font-size`/`gap`/`border-radius`, renaming CSS classes, changing icon sizes, updating `className` for styling, modifying Tailwind utility classes.

## What it controls

`test-strategist` must include only the **business logic side** in the Requirement Spec scenarios.

### Explicitly excluded from all scenarios

The following categories must **never** appear as `Then` assertions, `Given` preconditions, or acceptance-criteria coverage in any spec produced for a mixed ticket:

- Pixel / spacing values: `margin`, `padding`, `top`, `left`, `bottom`, `right`, `gap`, `width`, `height` (unless the dimension directly determines feature visibility, e.g. a component is zero-height and therefore invisible).
- Color and typography: `color`, `background-color`, `font-size`, `font-weight`, `line-height`, `border-radius`, `opacity`.
- CSS class names used purely for styling (not for identity/testid).
- Icon size or decorative icon choice.
- Layout alignment ("text should be centered", "icon is right-aligned").

### Acceptable business-logic assertions

- A component is **visible** or **hidden** (not *how large* or *what color*).
- A user action triggers the correct **state transition** or **navigation**.
- The correct **data** is displayed (label text, count, status), not how it is styled.
- A **permission gate** opens or closes the feature for the right role.
- An **API call** is made (observable via network tab or the test verifying the result data).

## How test-strategist must document this

In the spec's **Out of scope** section, add:

> **Visual layout** — This ticket also includes CSS/spacing/color adjustments (see PR diff lines: `<file>:<lines>`). These are excluded from the E2E spec per project rule `ui-logic-mixed-scope`. Visual regressions should be covered by screenshot-diffing (Chromatic / Playwright `toHaveScreenshot`).

## Known interactions

- If the **entire** ticket is visual with no logic, apply `pure-ui-skip` instead.
- This rule does not reduce the count of scenarios — one AC that mixes "show the panel" (logic, testable) with "panel has 8px top margin" (style, excluded) still produces one scenario that covers the logic half.
- The rule applies at the **assertion level**, not at the scenario level. Do not drop a scenario because it also mentions a visual tweak — keep the scenario and drop only the style assertion.
