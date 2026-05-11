# feature-case-agent

**Flag key:** `feature-case-agent`  
**Gates:** app-v2 — the Case Agent UI (`src/packages/app-v2/`)

## When to require this flag

Enable `feature-case-agent` whenever:
- The ticket description mentions "app-v2"
- Any changed file in the PR lives under `src/packages/app-v2/`

Tickets will not always state this flag explicitly. Infer it from the code path.

## What it controls

`feature-case-agent` activates the entire app-v2 rendering path. Without it, routes that serve AI-first cases fall back to the classic Portal UI. Any scenario exercising a component under `app-v2/` is silently untestable if this flag is off — the route will render but show a different component tree.

## Notes

- app-v2 is only rendered for AI-first cases (`job_meta.ai_first = true`). So `feature-case-agent = ON` is necessary but not sufficient — you also need an AI-first case (data gate, not a flag).
- The flag's MobX getter is typically `featureStore.isCaseAgentEnabled` or similar — follow it to confirm the underlying flag key if the diff uses a getter wrapper.
