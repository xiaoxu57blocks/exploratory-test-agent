---
name: create-case
description: Create a new test case in the Supio prod test tenant via the /create-case UI, with sensible defaults for fixture files, case type, and other form fields. Usage `/create-case [case-name]`. Drives the browser via Chrome DevTools MCP. Default fixtures are pulled from the team Drive cache so no human intervention is needed for the common path.
---

# /create-case

You drive the Supio portal's `/create-case` flow to create a new AI-artifact-first test case end-to-end. The user invokes this when a test scenario needs a brand-new case in a known starting state — typically when the spec's Data setup says "create a new case named `deqtest_<topic>_<run-id>` and upload fixtures".

This skill is **deterministic and quiet**: it does not ask the user to pick fixtures or case type unless they explicitly override defaults. The defaults below are what a typical AI-artifact-first scenario needs.

## Argument

- `[case-name]` (optional): the Case name field. If omitted, derive a sensible one — for ad-hoc invocations use `deqtest_create-case_<timestamp>`; if the user is mid-`/test-tickets` run, use `deqtest_<ticket-id-lowercase>_<run-id>` (e.g. `deqtest_sup-7623_2026-05-08_1524`).

## Defaults (apply unless user overrides)

| Field | Default | Why |
|---|---|---|
| Connector | **No connector** | Strips the Case ID requirement and avoids touching external systems (Litify, Filevine, etc.). |
| File source | **Upload from my computer** | Local upload is the most reliable path; cloud-source flows depend on connector auth. |
| Case type | **MVA** | Most AI-first scenarios on the test tenant use MVA. Stage auto-fills. |
| Demand letter | **none** | Not needed unless a scenario explicitly asserts on demand-flow behavior. |
| Fixtures | **`Police Report.Pdf` + `MRnMB.pdf`** | These two together cover incident, medical-record, medical-bill, and treatment event types — enough for the AI-first pipeline to produce a non-empty `timelineDocumentIds[]` and exercise extracting → postprocessing → empty. Both live in the team's `Supio QA` shared drive under the `AUTO/` subfolder. |

The default fixture list lives in `fixtures/manifest.json`. The two defaults are pulled from the team's `Supio QA` shared drive (folder `0ABN1KXZHE2OUUk9PVA`, subfolder `AUTO` = `1-KrKSmynJ_KhqSYstEttxrw6RnqHsmDq`). Update `manifest.json` when the canonical names change — the skill reads names from there.

### Google Drive setup (first-run, per machine)

`get-fixture.py` downloads via Drive API using OAuth, not public links — the Drive content is access-controlled. First time you run `/create-case` on a fresh machine you need:

1. `.claude/google-oauth-client.json` — Desktop OAuth client config from GCP Console. See README's "Google Drive setup" section.
2. Run once: `scripts/google-drive.py auth` — opens the browser, asks you to grant `drive.readonly` to the OAuth client. The token caches to `.claude/google-oauth-token.json` (gitignored, mode 0600). Refresh-token flow takes over after that — you won't see the browser again unless you revoke access in your Google account settings.

If `get-fixture.py` returns `{"ok": false, "stage": "drive_helper_failed", "exit_code": 4, ...}` it means the cached token is missing — re-run the `auth` step.

If the spec under test asserts on event types those two fixtures do **not** cover (e.g. `wage_loss`, a stand-alone `medical_bill`, an `imaging` study), add the relevant fixture to the upload set:
- Read `scripts/get-fixture.py --list` to see what's pre-mapped in the manifest.
- If the needed type isn't pre-mapped, add a new entry to `fixtures/manifest.json` (Drive file id + `covers_event_types`) and let the script pull it. Don't hard-code Drive ids inside this skill.

## Optional flags

- `--with <fixture-name>[,<fixture-name>...]` — replace the default fixture set with this list. Each name must exist in `fixtures/manifest.json`. Example: `/create-case deqtest_x --with "Incident_Report.pdf,MedicalRecords.pdf,bill UMPC.pdf"`.
- `--add <fixture-name>[,<fixture-name>...]` — keep defaults and append these. Example: `/create-case deqtest_x --add "bill UMPC.pdf"` to add a discrete medical-bill event on top of the defaults.
- `--type <case-type>` — override the case type (e.g. `--type "Premises Liability"`). Default MVA.
- `--no-demand-letter` (default; included only for explicitness) / `--with-demand-letter` — currently the form has no demand-letter checkbox under the No connector + manual upload path, so `--with-demand-letter` is informational.

## Pre-flight

Before any browser action:

1. The Chrome DevTools MCP is connected (the test-tickets pipeline should already have set this up; if invoked standalone, call `mcp__chrome-devtools__list_pages` first to confirm).
2. The user is signed in to `https://portal.supio.com` as the external test account (Supio Test). If `/create-case` redirects to login, fail with a clear "log in via the test-env credentials, then re-run" error rather than attempting to log in here — auth is the test-executor's job, not this skill's.
3. The `feature-ai-artifact-first` flag is on for that user (verify by reading `localStorage.enabledFeatureFlags`). If missing, refuse — the AI-first surface won't render and the panel under test will never mount; the user needs to enable the flag (or the executor's pre-flight should have done so).
4. Resolve every fixture name to a local cached path:

   ```bash
   scripts/get-fixture.py --name "<fixture-name>"
   ```

   If a fixture isn't in cache, the script downloads it from Drive into `fixtures/cache/<name>.pdf`. The script's stdout is one line of JSON; parse it. On `ok: false` with `stage: download_returned_non_pdf`, fall back to asking the user to drop the PDF into `fixtures/cache/` manually, then retry. **Don't try to scrape Drive's UI yourself — the script handles that path or fails clearly.**

## Workflow

1. **Announce**: `Creating case "<resolved-case-name>" with fixtures [<list>] (type=<type>, no connector).`
2. Navigate: `mcp__chrome-devtools__navigate_page` to `https://portal.supio.com/create-case`.
3. `wait_for(["Case name", "Connector"], timeout=15000)` so the form has hydrated.
4. Take a snapshot. Click **No connector** and **Upload from my computer** radios. (Use `evaluate_script` to click radios by `value="manual"` / by label text "No connector" — Ant Design's radio uids change between snapshots.)
5. Fill **Case name** with the resolved name. Use `mcp__chrome-devtools__fill` against the textbox uid from the latest snapshot.
6. Open the **Case type** combobox, type the case type (default `MVA`), press Enter to commit.
7. For each resolved fixture path, call `mcp__chrome-devtools__upload_file` against the drop-zone button uid. The form supports calling `upload_file` once per file — multiple PDFs append to the staged list.
8. Snapshot to confirm: every fixture name appears in the staged file list with the expected size; "Total: N files" matches.
9. Click **Create case**. The button is enabled when Case name + Case type are set and at least one file is staged.
10. `wait_for(["Uploading", "Case created", "Case Activity", "Overview"], timeout=30000)`.
11. After upload completes, the URL becomes `/timeline/<case-id>?t=overview`. Capture `<case-id>` from the URL — that is the value the rest of the spec (and any localStorage key like `aiTimelinePanelClosedInDoneState_<case-id>`) needs.
12. Return a one-line summary to the orchestrator: `Created case <case-id> "<case-name>" with N fixtures. Pipeline starting; status will transition empty → extracting within ~30s.`

## Hard rules

- **Never invent ticket / case ids.** If `case-name` resolution depends on a ticket id and the user didn't pass one, ask once. Do not autopopulate from "the most recent run" — that has bitten us before with the wrong case.
- **Test tenant only.** The flows here write to prod. The test account `user@test.supio` lives in an isolated tenant per `CLAUDE.md`'s test-environment rule; never invoke this skill while signed in as a real internal user.
- **Don't ask the user to pick fixtures by default.** Defaults are good enough for AI-first scenarios; only prompt if (a) the user explicitly passed `--with` with names not in the manifest, or (b) `get-fixture.py` returned `ok: false` and the user needs to drop a file manually.
- **Don't hardcode Drive file ids inside this skill or the script's caller.** All ids live in `fixtures/manifest.json`; the manifest is the contract.
- **Don't bypass `feature-ai-artifact-first`.** A case created without that flag at create-time is permanently bound to the legacy pipeline (observed regression) and the AI-first panel will never mount on it. If the flag is off, refuse.

## Anti-patterns

- ❌ Reading the Drive folder's HTML / a11y tree to enumerate files — that path is fragile, virtualized, and language-locale-dependent. Use the manifest.
- ❌ Calling `upload_file` with a path outside the workspace root (Chrome DevTools MCP will refuse).
- ❌ Falling back to "any PDF will do" if a manifest fixture isn't downloadable — the AI-first pipeline needs real medical-shaped content to produce non-empty `timelineDocumentIds[]`. A junk PDF will give you a case stuck at `status: 'empty'` and no panel.
- ❌ Filling Case ID under the No-connector path. That field is hidden by the form when `connector === none`; trying to interact with it crashes the snapshot.

## Extending the manifest

When a future PR introduces a new event type the defaults don't cover:

1. Find the right fixture in the team Drive folder (`https://drive.google.com/drive/u/0/folders/1-KrKSmynJ_KhqSYstEttxrw6RnqHsmDq`). Note its file id from the URL when you click into the file.
2. Add an entry to `fixtures/manifest.json` with `drive_file_id` + `covers_event_types`.
3. Run `scripts/get-fixture.py --name "<new-name>"` once to seed the cache.
4. Update the **Defaults** table above only if the new fixture should be part of the *default* set — otherwise just leave it in the manifest and let scenarios opt into it via `--with` / `--add`.
