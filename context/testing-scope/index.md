# Testing Scope Rules

Rules that govern what gets tested and at what level of detail.

| Rule | What it controls | Detail file |
|------|-----------------|-------------|
| `pure-ui-skip` | Skip tickets that are purely visual/layout changes; still post a comment explaining why | [pure-ui-skip.md](pure-ui-skip.md) |
| `ui-logic-mixed-scope` | When a ticket mixes business logic and UI tweaks, test only the business logic; exclude layout/spacing assertions | [ui-logic-mixed-scope.md](ui-logic-mixed-scope.md) |
