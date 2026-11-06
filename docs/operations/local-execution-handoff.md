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

Codex is the chosen upload operator, **not a new permanent Drive integration**. Availability of Drive access from Codex has not yet been proven.

## ChatGPT review and acceptance

Share the real Drive file links/IDs here. ChatGPT retrieves actual remote files through connected Drive, compares uploaded files to their remote SHA-256 manifest and checks the uploaded manifest identity against the locally recorded hash. If remote bytes cannot be fetched, report **PARTIAL**; do not invent a successful round trip. Independently verify code/test assertions against actual GitHub revisions, diffs and CI.

**First real acceptance:** Run one harmless real prompt in OpenCode or Freebuff (for example, summarize the SignalForge development workflow without editing code), obtain its sanitized `report.md` under a fresh `/tmp/signalforge-.../` directory, inspect and hash it, have Codex upload to Drive, and review/read back here.

- **HANDOFF_VERIFIED:** actual TUI execution + authenticated Drive upload + independently downloaded matching bytes/hashes + ChatGPT review.
- **PARTIAL:** one or more checks missing, including no proof of Codex Drive access.
- **BLOCKED:** unsafe output, mismatched hashes, invalid destination or access/safety failure.

A transport acceptance test is not trading qualification, strategy validation, paper/live approval or merge readiness. PR #248 remains draft until the repository's full DoD and issue criteria are satisfied.
