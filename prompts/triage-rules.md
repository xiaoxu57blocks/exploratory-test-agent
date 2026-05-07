# Triage Rules — Reference

Read this when a ticket looks ambiguous and you (the `test-triage` agent) need to decide.

## Layer 1 — Deterministic skip rules

### Skip if state is terminal-non-shipped
- `Cancelled`
- `Won't Do`
- `Duplicate`

### Skip if labels indicate non-product work

| Label | Example signal |
|-------|----------------|
| `tech-debt` | Internal refactor, no user-facing change |
| `spike` | Investigation, no implementation |
| `chore` | Build/dep upgrade, repo housekeeping |
| `infra` | CI/CD, deployment, observability |
| `docs` | Documentation only |
| `internal-tooling` | Tools used by engineers, not end users |

### Skip if text indicates the work is being abandoned

Regex (case-insensitive, applied to title + description + comments from assignee/admins):

```
/(deprecated|will be (redone|deprecated|removed)|major refactor (coming|incoming)|废弃|大改|不需要测)/
```

Examples that match:
- "This will be deprecated in Q3"
- "Major refactor coming — don't extend"
- "废弃，请勿基于此实现"

Examples that don't match (do NOT skip):
- "Replaces the old upload flow" (replacing != deprecating the new feature)
- "Refactor the upload form" (refactor of subject, not "refactor coming")

## Layer 2 — LLM judgment

### Test if the change is user-observable

User-observable means **at least one** of:
- A UI change (new button, changed copy, new screen, modified layout)
- An API response change visible from the UI (different data, different format)
- A change in a business rule the user can trigger (validation, calculation, side effect)
- An integration change (new connector, modified webhook behavior)

### Skip if the change is invisible to users

Strong signals for "invisible":
- Title/description explicitly says "no behavior change", "refactor only", "internal cleanup"
- PR title contains `refactor:`, `chore:`, `style:`, `perf:` (and the body confirms no behavior delta)
- The diff (if accessible via Linear PR metadata title) is a rename, type alias, or test-only change

**Important**: Absence of evidence is NOT evidence of "invisible". A ticket with a sparse description and no PR is `low confidence`, not `skip`.

## Confidence calibration

| Confidence | Use when |
|------------|----------|
| `high` | Title + description + at least one PR title clearly describe a user-facing change. Or, a deterministic rule fired. |
| `medium` | Description is sparse, but project label or PR title gives a strong signal about scope. |
| `low` | Ticket is mostly empty (no description, no comments, no PR title with content). Cannot judge without more info. |

If confidence is `low`, you must add it to `needs_user_review`. Do not guess a decision and label it high confidence to avoid the pause.

## Clustering

### Group tickets into one unit when

- They share a Linear `parent` issue
- They share the same `project`
- Their titles reference the same feature (e.g. both mention "case archive")
- A comment on one ticket references another by ID (e.g. "blocked by LIN-1235")
- Their PR titles modify overlapping modules

### Keep them separate when

- They share only a label like `bug` or `enhancement` — too generic
- They were created in the same week but otherwise unrelated
- One depends on the other but tests different surfaces

When in doubt, **keep separate**. Over-clustering creates spec bloat and dilutes focus.

## Anti-patterns

- ❌ Skipping a ticket because the description is empty. Empty != skippable. Use `low` confidence and ask the user.
- ❌ Bundling 8 tickets into one unit because they share a project label. Test units of >4 tickets are usually wrong.
- ❌ Inventing scope to justify "test" on a ticket that has no description. If you have nothing to test, say so.
