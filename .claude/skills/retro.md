---
name: retro
description: Read a finished /test-tickets run's intervention log and produce a retro that lists every place the agent had to be course-corrected, paired with concrete proposals for which agent/skill/template file to change so the same correction isn't needed next time. Outputs a local-only `06-retro.md`. Usage `/retro <run-id>`.
---

# /retro

You are looking back at a single `/test-tickets` run and asking one question per intervention: **what should the agent have done without being told, and which file's rules need to change to make that happen?**

This is not a test report. The PASS/FAIL of scenarios is already in `04-run-<unit_id>/result.json` and on Linear. `/retro` only cares about **agent behavior gaps**.

## Arguments

- `<run-id>` (required): the run directory under `artifacts/`. If missing, ask before doing anything else.

## Inputs

For the given run-id, read:

- `artifacts/<run-id>/interventions.jsonl` — every user prompt during the run (captured by the `UserPromptSubmit` hook) plus any `kind:"orchestrator_note"` entries the orchestrator left behind. **If this file is missing or empty, stop and tell the user — there is nothing to retro.**
- `artifacts/<run-id>/04-run-<unit_id>/trace.jsonl` — what the executor actually did. Useful for grounding interventions in the action context that triggered them.
- `artifacts/<run-id>/03-spec-<unit_id>.md` — the spec the executor was working from. Many interventions point back to gaps in this file.
- The agent and skill files under `.claude/agents/` and `.claude/skills/` — the targets of any proposed changes.
- `prompts/strategy-template.md` — also a possible target.

## What counts as a real intervention

You will see far more user prompts in `interventions.jsonl` than there are real interventions. Filter LLM-side, not via keywords. A real intervention is:

- The user **corrects** the agent ("不对", "stop", "actually no", "shouldn't you have…", "为什么没有…").
- The user **supplies missing context** the agent should have looked up itself ("the flag name is in the PR", "you need to check feature-case-agent").
- The user **redirects the strategy** in a way that suggests the spec or agent rules pre-committed to the wrong thing ("re-scope to just disconnect/reconnect", "don't test that on the legacy assistant").
- The user has to manually do something that should have been automatic ("I'll click the dev panel myself", "let me complete the OAuth").

Not interventions:

- The user picking a normal option from an `AskUserQuestion` prompt where every option is a reasonable path forward.
- The user answering a clarification you legitimately couldn't have known (e.g. "use the test tenant on prod" — not in the spec, has to be asked).
- The user expressing approval ("looks good", "yes post it").
- Off-topic chat unrelated to the run.

When in doubt, lean toward including it and let the user reject the proposal. False positives waste 30 seconds; false negatives mean the rule never gets written.

## Output

Write `artifacts/<run-id>/06-retro.md` with this structure:

```markdown
# Retro — <run-id>

**Run:** <run-id> • **Tickets:** <list> • **Outcome (from result.json):** <PASS|FAIL|...>
**Total user prompts captured:** <N> • **Real interventions identified:** <M>

## Interventions

### 1. <one-line summary of what went wrong>

**Phase:** <phase from trace.jsonl or orchestrator_note>
**User said:** "<verbatim, trimmed if long>"
**What the agent had been doing:** <2-3 sentence summary grounded in trace + orchestrator_note>
**Why this is a rule gap, not a one-off:** <why it would happen again on the next ticket>

**Proposed change:**
- File: `.claude/agents/<x>.md` (or skill / template)
- Section: <heading the change goes under>
- Diff sketch:
  ```
  + <new rule, in the imperative voice the file uses>
  ```
- Confidence: high | medium | low (low = "this might just be one-off, judge yourself")

### 2. ...

## Interventions considered but rejected

- "<prompt snippet>" — <one-line reason it isn't a rule gap, e.g. "spec genuinely required a clarifying question about test data">

## Cross-cutting observations

<Optional. Use this only if 3+ interventions in the run share a root cause that no single file's rule will fix — e.g. "the strategist consistently underspecifies the chat surface, suggesting `prompts/strategy-template.md` needs a 'Surface' field". Skip the section if there's nothing of this shape.>
```

## Workflow

1. Confirm `artifacts/<run-id>/interventions.jsonl` exists. If not, stop with a clear message.
2. Read it. Read the trace, spec, and result for the same run.
3. For each user-prompt entry, decide: is this a real intervention by the rules above? If yes, find the matching `orchestrator_note` (close in time) for the "what the agent did next" half. If no orchestrator note exists, infer from trace.
4. For each real intervention, look at the relevant agent/skill/template file and draft a specific addition. The rule must be **concrete and actionable** — "the strategist should be more thorough" is useless; "the strategist should call `mcp__linear__get_diff` on every GitHub attachment in 01-fetch.json and grep for `feature-*`" is useful.
5. Write `06-retro.md`. Do not modify any agent or template file directly — `/retro` is read-only by design. The user reviews the retro and applies whichever proposals they agree with.
6. Return a one-paragraph summary: how many interventions identified, how many rejected, and which 1–2 are most worth the user's attention.

## Hard rules

- **Read-only.** Do not Edit/Write any file under `.claude/agents/`, `.claude/skills/`, or `prompts/`. Your only write target is `artifacts/<run-id>/06-retro.md`.
- **Quote the user verbatim.** Do not paraphrase what the user said in the "User said" field — even if it was in another language.
- **No fake diffs.** If you propose a diff, the file path and surrounding section must actually exist. If you're proposing a brand-new section, say so explicitly.
- **One file per proposal.** If a single intervention's fix touches multiple files, list them as separate proposals so the user can accept some and reject others.
- **No retros for runs without an interventions.jsonl.** Tell the user to re-run the pipeline with the hook active.

## Anti-patterns

- ❌ Treating every user prompt as an intervention. Most are not.
- ❌ Generic recommendations ("be more careful", "improve testing"). Every proposal must name a file and a section.
- ❌ Proposing a rule that already exists. Read the target file first; if the rule is there and was ignored, the right fix is somewhere else (often the orchestrator's hard rules), not duplication.
- ❌ Editing agents/skills directly. Output is a markdown report; the user applies the changes.
