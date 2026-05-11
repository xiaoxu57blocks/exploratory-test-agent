# context/

This directory holds **shared business rules** that agents consult at runtime and that the team maintains together. Rules here are loaded on-demand (not at session start), so keep each file focused on one topic.

## Structure

```
context/
  feature-flags/
    index.md        ← one-line entry per flag; always update this first
    <surface>.md    ← detail file per Portal surface / package
  <topic>/          ← add new topic directories as needed
    index.md
    ...
```

## How to add a new business rule

1. **Pick the right directory.** Feature flag rules go under `context/feature-flags/`. For a new topic (e.g. user-role behaviour, case-type constraints), create a new subdirectory: `context/<topic>/`.
2. **Add a detail file.** Name it after the surface or concept it describes (e.g. `app-v2.md`, `settlements.md`). Include:
   - When this rule applies (the trigger condition)
   - What it controls or implies
   - Any known interactions with other flags / rules
3. **Update the index.** Add one row to `context/<topic>/index.md` in the format:
   ```
   | `key-or-name` | What it gates / what it means | [detail-file.md](detail-file.md) |
   ```
4. **Keep CLAUDE.md clean.** Do not paste rule content into CLAUDE.md — it already points agents to this directory. CLAUDE.md is for architecture and hard rules only.
5. **Commit with a `context:` prefix**, e.g. `context: add feature-settlements flag rule`.
