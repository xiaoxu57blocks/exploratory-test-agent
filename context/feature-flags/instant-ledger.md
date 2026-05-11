# feature-ai-artifact-first

**Flag key:** `feature-ai-artifact-first`  
**Gates:** AI-first case rendering in instant-ledger (`src/packages/instant-ledger/`)

## When to require this flag

Enable `feature-ai-artifact-first` whenever:
- The scenario exercises an AI-first case (`job_meta.ai_first = true`) through the instant-ledger path
- The ticket or diff references `APLedgerView`, `LedgerHeader`, or other instant-ledger components with an `isAiFirst` condition

## What it controls

Without this flag, instant-ledger will not render AI-first cases — the route may load but the AI-specific UI path is never reached. The flag is the surface-level gate; `job_meta.ai_first = true` is the data gate that activates the AI-first branch within that surface.

## Interaction with feature-case-agent

These two flags govern different rendering paths and are typically mutually exclusive per scenario:

| `feature-case-agent` | `feature-ai-artifact-first` | Path taken |
|---------------------|-----------------------------|------------|
| ON | ON | app-v2 (Case Agent UI) |
| OFF | ON | instant-ledger with AI-first case support |
| OFF | OFF | classic Portal UI, no AI-first case support |
