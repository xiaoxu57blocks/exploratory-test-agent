---
name: archive-to-portal
description: Manually archive a passing test from a run's artifacts to the portal-ui-automation repo. Usage `/archive-to-portal <run-id>/<unit-id>`. Adapts the generated.spec.ts to portal's conventions and creates a branch in $PORTAL_REPO_PATH. Never auto-pushes — the user reviews and pushes themselves.
---

# /archive-to-portal

You are orchestrating a one-shot archival from this repo's `artifacts/` to the portal-ui-automation repo.

## Argument

`<run-id>/<unit-id>` — e.g. `2026-05-07_1430_SUP-7152/unit-1`

If missing or malformed, ask the user. Do not guess.

## Pre-flight

Before invoking the archiver agent, sanity check yourself:

1. The path `artifacts/<run-id>/04-run-<unit-id>/generated.spec.ts` exists.
2. The path `artifacts/<run-id>/04-run-<unit-id>/result.json` exists and contains `"passed_primary": true`. If not, refuse — the user can pass `--force` to override (and you must surface a warning if they do).
3. `$PORTAL_REPO_PATH` is set and points to a git repo.

If any check fails, print a clear error and stop. Do not proceed.

## Workflow

1. Announce: "Archiving <unit-id> to portal repo at `$PORTAL_REPO_PATH`"
2. Invoke the `portal-archiver` agent with the run-id and unit-id.
3. Surface its summary verbatim. Do not paraphrase the branch name, file path, or next-step commands.

## Hard rules

- **Manual only.** This skill must never be invoked automatically by `/test-tickets` — the user has to explicitly run it.
- **Never push.** Let the archiver create the branch and commit; pushing is the user's call.
- **Never archive a failed run** unless the user passes `--force` and you've shown them a warning.
- **One unit per invocation.** Don't try to batch multiple units in one go — each archival should be a reviewable unit of work.

## Anti-patterns

- ❌ Inferring the run-id/unit-id from "the most recent run" if the user didn't specify
- ❌ Editing files in `$PORTAL_REPO_PATH` outside of the archiver
- ❌ Running `npx playwright test` after archival "to verify it works" — the user will do that
