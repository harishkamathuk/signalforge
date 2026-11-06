# SF-247 — OpenCode / Freebuff → /tmp → Codex → Google Drive → ChatGPT

## Approved workflow

OpenCode and Freebuff already work in WSL2. Use either TUI for routine, low-value tasks, and Codex for high-value tasks **and for uploading reviewed outputs** to Google Drive. ChatGPT reviews the uploaded results and verifies any implementation assertions against GitHub. Do not install, benchmark or wrap the existing agents; no executor, daemon, model router, Drive watcher, or general-purpose task-schema platform.

GitHub remains the durable source of truth for code, requirements, PRs and CI. Google Drive is a transport mechanism. Do not move credentials, database contents, protected Delta/market data, raw terminal transcripts or unfiltered logs off WSL2.

## The output convention

One task, one unique directory: `/tmp/signalforge-sf247-pilot-001/` (substitute a fresh task ID for each task and retry).

- `report.md` — sanitized task summary with task/issue ID, agent and model **if known**, initial and final Git SHAs, files changed, commands/tests with observed results, unresolved issues and required approvals. Explicitly distinguish unverified agent claims from observed facts.
- `test-summary.txt` — optional **sanitized** test summary, not full raw logs. Additional reviewed `.md`, `.txt`, or `.json` files may be included.
- `sha256-manifest.json` — optional but recommended write-once manifest generated after human review.

The staging directory is temporary: preserve anything essential separately in existing protected local storage and GitHub. Never automatically upload all contents of an agent session or local data directory.

## Prompt A — paste into OpenCode or Freebuff

> Work on SignalForge **[ISSUE/TASK]** in the existing WSL2 checkout, within **[APPROVED SCOPE]**. Follow the current GitHub issue, standards and repository DoD. Carry out routine scoped work and tests through this TUI. Do not alter trading rules, persistence/recovery semantics, protected market data or credentials; do not push/merge, install dependencies, run destructive commands or perform high-impact operations without explicit operator approval.
>
> When finished, create **/tmp/signalforge-[TASK-ID]/report.md** with a concise *sanitized* report recording task ID, actual agent/model if known, Git base/head SHA, edited paths, test commands with exit statuses (or NOT_RUN), results, blockers, approvals and any unverified assertions. Optionally create **test-summary.txt** with sanitized test output. Do not transfer files or reveal credentials, protected market data or full raw logs. Tell me the output directory.

No further agent setup or integration is needed. Inspect the actual output before transfer.

## Prepare and verify the handoff

From the current SignalForge feature checkout, after reading each staged file and removing sensitive material:

```bash
python -m scripts.handoff_manifest create /tmp/signalforge-sf247-pilot-001
python -m scripts.handoff_manifest verify /tmp/signalforge-sf247-pilot-001
```

The minimal Python 3.12 standard-library helper only creates/verifies a SHA-256 manifest. It enforces one direct child of `/tmp`, safe basenames/extensions, regular files only (no symlinks), at most 20 files, 1 MiB per file and 4 MiB combined, and a mandatory `report.md`. The manifest is write-once. It does **not** execute agents, clean sensitive content or attest the truth of a report. Use a new directory after changes to a manifested handoff.

## Prompt B — paste into Codex for transfer

> **Transfer task only. Do not edit SignalForge source or run development work.** Inspect **/tmp/signalforge-[TASK-ID]/** and upload only its already reviewed, sanitized files. First run the existing repository helper to verify **sha256-manifest.json** against the staged files. Do not upload secrets, raw logs, market datasets or database files.
>
> Using an **already available authenticated Google Drive method**, upload the reviewed files to the existing **ChatGPT / SignalForge / 02 Execution Reports** folder, ID **1HaPGxwf6zTEgaJ8tFtGZnOxaKBWX9cMw**. Do not invent a Drive CLI, install a sync agent, broaden sharing, overwrite a previous upload or use unattended execution. If no authenticated upload method is available, **STOP and report the blocker**. Do not request credentials in the transcript.
>
> Return the actual Google Drive file IDs/links and the local SHA-256 of **sha256-manifest.json**. Upload success is not round-trip verification: ChatGPT must independently retrieve and verify the uploaded bytes.

Codex is the chosen upload operator, **not a new permanent Drive integration**. The first authenticated Codex-to-Drive transfer was independently verified for SF-247; future sessions must still use their own valid authenticated access.

## Zero-link ChatGPT pickup (single active task)

The operator does **not** need to copy Drive file links or IDs into ChatGPT.
When asked to **"process the latest SignalForge handoff"** (or equivalent),
ChatGPT will use the connected private Drive account to inspect the existing
`ChatGPT / SignalForge / 02 Execution Reports` folder (ID
`1HaPGxwf6zTEgaJ8tFtGZnOxaKBWX9cMw`), identify the most recently
uploaded **complete** report/manifest handoff, fetch the actual raw bytes,
verify the manifest identity and each file SHA-256, and review the report
against GitHub before responding.

For the single-task operator workflow, choose the **newest complete and
unprocessed handoff**, rather than simply the newest individual Drive file:
the final uploaded file might be a manifest, report or attachment. A manifest
must identify its report and their bytes must match. If several uploads reuse
generic filenames (`report.md`, `sha256-manifest.json`), select a matching
pair using upload metadata, task ID/report contents and hashes; do not
silently combine unrelated runs. If a reliable match cannot be established,
**STOP and describe the ambiguity**, instead of choosing files based only on
their sort order. Record the processed task ID and Drive IDs in the GitHub
issue/PR to avoid silently reprocessing previous evidence.

This is **on-demand**, only when the user requests processing in ChatGPT.
There is no background watcher, automatic trigger, queue or claim that
ChatGPT can see unuploaded local `/tmp` files. Each session checks Drive
afresh, so no assumption about previous chat memory is necessary.
The first verified pair is the SF-247 pilot (`signalforge-sf247-pilot-001`);
subsequent handoffs should use a new unique task ID. No new folder or
Drive upload integration is required.

## ChatGPT review and acceptance

Ask ChatGPT to process the latest handoff; it identifies the appropriate report/manifest pair in the connected Drive folder. ChatGPT retrieves actual remote files through connected Drive, compares uploaded files to their remote SHA-256 manifest and checks the uploaded manifest identity against the locally recorded hash. If remote bytes cannot be fetched, report **PARTIAL**; do not invent a successful round trip. Independently verify code/test assertions against actual GitHub revisions, diffs and CI.

**First real acceptance (completed 2026-11-06 for SF-247):** The pilot used one harmless real prompt in OpenCode or Freebuff (a read-only SignalForge development-workflow summary) and a sanitized `report.md` under `/tmp/signalforge-sf247-pilot-001/`. Codex uploaded the report and its manifest to the existing Drive folder. ChatGPT independently fetched both raw files and verified the exact local manifest SHA-256 `82507654d7550a4d8bd69d59f56e1bea29c094143a989a3129c54f6d02017486`, the report digest and the folder ID. Evidence and limitations are recorded in GitHub issue #247 and PR #248. This verifies this handoff, not the independent truth of all TUI-reported commands.

- **HANDOFF_VERIFIED:** actual TUI execution + authenticated Drive upload + independently downloaded matching bytes/hashes + ChatGPT review.
- **PARTIAL:** one or more checks missing, including no proof of Codex Drive access.
- **BLOCKED:** unsafe output, mismatched hashes, invalid destination or access/safety failure.

A transport acceptance test is not trading qualification, strategy validation, paper/live approval or automatic PR merge approval. Apply the repository's full DoD and review gates to each PR.
