# SF-247 — Operator-controlled local execution/evidence handoff

## Supervised local coding-agent development — approved primary workflow

**Plain English:** The intended operator experience is to delegate an approved
development task to **one local coding agent** in WSL2, not to manually type each
Git and Python command. The agent may edit files, run focused tests, diagnose
failures and prepare local commits **within the task's approved scope**. The
operator starts and supervises the session and authorizes sensitive actions.
ChatGPT prepares/reviews tasks and evidence, but **does not directly control
the WSL2 process**.

The existing `python -V` helper below remains a **smoke/transport pilot**.
It cannot be presented as acceptance of supervised coding-agent development.

### Agent selection and safeguards

On WSL2, first identify whether Codex or another *one chosen* local agent CLI
is already installed and whether its authentication/usage limits are acceptable.
Do not assume any agent is free, already installed, or configured. Reuse the
existing WSL2 repository and virtual environment.

Before the operator launches it, verify the selected agent's **actual**
workspace/sandbox, approval, network and credential-access settings. Configure
the agent to require operator approval for destructive Git, remote pushes,
dependency installation, network access, access to protected datasets,
database changes and out-of-scope operations. No unattended mode or automatic
agent startup from a Drive file. Do not use an option granting unrestricted
filesystem/host access to avoid approval prompts.

**Security distinction:** JSON task restrictions and textual prompts are
*instructions*, not a sandbox or proof that access controls have been enforced.
The agent's sandbox and operator approvals are separate technical controls.
If those cannot be verified, classify the exercise as **BLOCKED**.

### Agent task package

`scripts/local_agent_task_handoff.py` contains the v1 versioned task/report
schema, SHA-256 verification and fixed supervised permission boundaries.
It **does not launch Codex, execute code, publish files or access Drive**.
A task package contains task ID, GitHub issue, exact Git base SHA, scope,
allowlisted `docs/` or `tests/` paths, acceptance criteria, operator approval
conditions and an explicit prohibited-operation list.

Example: create a short local instruction file (review its contents before
use) under the existing ignored handoff root, such as
`.signalforge-data/handoff/pilot-instructions.txt`. For the pilot choose a
bounded **documentation-only** change on a disposable feature branch; do not
touch strategy code, database migrations, protected market data or order paths.

```bash
cd ~/dev/signalforge
source .venv/bin/activate
git status --short
git rev-parse HEAD

python -m scripts.local_agent_task_handoff prepare \
  --repo . \
  --task-id sf247-supervised-pilot-001 \
  --issue 247 \
  --task-file .signalforge-data/handoff/pilot-instructions.txt \
  --allowed-path docs/validation/sf247-pilot.md \
  --acceptance "Documentation change is reviewable" \
  --acceptance "Focused documentation check passes"
```

The command creates a **write-once** protected task JSON and prints its SHA.
Choose a new ID for a repeat; never overwrite an old task or evidence package.
Use `verify --task PATH` to validate any received JSON.

The operator then copies/passes the **verified task** to the chosen agent's
normal local interactive interface and starts a **supervised session**. The
agent should perform the task, collect its Git diff/test outcomes, and
prepare sanitized evidence in the operator-controlled protected location.
Use the agent's documented interaction/approval commands for the installed
version; do not invent CLI flags or make the task package directly executable.
The operator checks actual Git status/diff and test results before accepting
the agent's summary.

A matching report may be verified with:

```bash
python -m scripts.local_agent_task_handoff verify \
  --task .signalforge-data/handoff/agent-tasks/sf247-supervised-pilot-001.json \
  --report .signalforge-data/handoff/agent-reports/sf247-supervised-pilot-001.json
```

The agent report is a **sanitized declaration**, not cryptographic proof that
an agent really edited, tested, obtained approvals or ran within a sandbox.
Compare against independent Git diffs, actual test output and the observed
operator approval trail. A complete v1 report includes task identity/base
SHA, observed head SHA, changed-file list, bounded checks/exit codes,
operator-approval references, findings, classification and SHA-256.
The report file must remain Git-ignored and be created without overwriting
anything. Do not export raw logs or full protected data.

### Real acceptance gates

A `LOCAL_HANDOFF_READY` claim now requires **all**:

1. A chosen, authenticated local agent demonstrably installed on the real WSL2
   host with verified sandbox and supervisory approval settings.
2. A unique verified task package bound to the actual Git base SHA.
3. A real, **agent-performed** scoped development change and focused tests
   without manually typing each command.
4. Operator confirmation of Git diff, test status, approval/stop behavior and
   the sanitized, write-once report; its hashes match task identity.
5. An actual authenticated upload to the existing private Drive **02 Execution
   Reports** folder and independent retrieval/hash verification, where Drive
   is selected for the handoff.
6. GitHub PR/issue milestone evidence, adversarial review and repository DoD.

If only the smoke protocol works, disposition is **PARTIAL**. If agent sandbox
or protected-data boundaries cannot be established, disposition is **BLOCKED**.

---

## Plain English — legacy read-only smoke protocol

This is a **manual smoke-test handoff**, not remote execution. ChatGPT can exchange an
approved JSON request and a sanitized JSON report with the existing WSL2 workstation,
optionally through authenticated Google Drive. **Only the operator runs the command.**
Google Drive and ChatGPT cannot trigger or authorize execution automatically.

The first version permits only `python -V` (using the currently active Python
interpreter). It does not support arbitrary shell commands, historical-data reads,
PostgreSQL, brokerage actions, research qualification, or trading orders.

GitHub remains authoritative for code, issues, PRs, review and CI. WSL2 owns
local execution and original evidence. Google Drive is optional transport, not
a Git or market-data store.

## Source-controlled contract

Use `scripts/local_execution_evidence.py` from a trusted SignalForge checkout.

The v1 **request** contains exactly these fields:

- `version: 1`
- `request_id`: unique, safe alphanumeric/hyphen/underscore ID (8–64 chars)
- `issue`: positive GitHub issue number
- `repository: "harishkamathuk/signalforge"`
- `revision`: exact 40-character lowercase Git commit SHA
- `argv: ["python", "-V"]`
- `preflight`: fixed Git HEAD, trusted origin, clean tracked tree, ignored output
- `expected_exit_code: 0` and `expected_output: "Python 3.12.x"`
- `stop_conditions`: preflight failure, request mismatch, unsafe output
- `classification: "SANITIZED_SMOKE_ONLY"`
- `request_sha256`: canonical JSON SHA-256 excluding this field

The v1 **report** records the same request identity and execution contract, local revision, UTC start/end,
exit/termination, allowlisted version output and output digest, local PASS/FAIL,
`transport_status: "NOT_ATTEMPTED"`, classification and report SHA-256.

Canonical JSON uses UTF-8, ASCII-escaped strings, keys sorted, no insignificant
whitespace, strict JSON numbers, and SHA-256 excluding the self-hash field.
A trailing LF in the stored file is intentionally *not* hashed.

The report does **not** contain unrestricted stdout, stderr, environment contents,
absolute local paths, credentials or raw evidence. The helper has no network or
Google Drive dependency. Verification of a downloaded report checks the original
request and all report hashes, but a hash is **not a signature**: a malicious
actor who can replace both payload and hash can forge a new artifact. Restrict
Drive permissions and independently compare the locally recorded identities.

## One-time workstation preflight

From the **existing** WSL2 repository:

```bash
cd ~/dev/signalforge
git status --short
git branch --show-current
git remote -v
git rev-parse HEAD
source .venv/bin/activate
python --version
git check-ignore -v .signalforge-data/handoff/reports/probe.json
```

Do not reset/clean a dirty checkout. Do not reinstall dependencies to satisfy this
smoke test unless an actual missing dependency is shown. The helper uses the
Python standard library and requires Python 3.12 for the current acceptance.

Do not run destructive PostgreSQL tests against the preserved `signalforge_dev`
database. This workflow does not require PostgreSQL.

## Prepare and approve a request

From the trusted repository root, with the exact commit SHA from `git rev-parse HEAD`:

```bash
umask 077
python scripts/local_execution_evidence.py prepare \
  --issue 247 \
  --revision "$(git rev-parse HEAD)" \
  --request-id sf247-wsl-smoke-0001 \
  --repo .
```

Request creation is write-once. Do not reuse IDs or overwrite evidence. Review the
JSON, request hash, issue, exact Git commit, command and classification before
execution. If a request was obtained from Drive, save it only to the protected
local request area and verify its expected hash **independently** against the
GitHub/ChatGPT coordination record. Downloading never authorizes execution.

Execute only with explicit request-ID approval:

```bash
python scripts/local_execution_evidence.py run \
  --repo . \
  --request .signalforge-data/handoff/requests/sf247-wsl-smoke-0001.json \
  --approve-request-id sf247-wsl-smoke-0001
```

The helper rejects an incorrect repository remote, dirty tracked working tree,
wrong Git HEAD, invalid request, a command other than Python version, an
unignored report location and report overwrite. No shell execution occurs.

Local output (write-once) is:

` .signalforge-data/handoff/reports/sf247-wsl-smoke-0001.json `

with no initial space in the actual pathname.

Verify locally:

```bash
python scripts/local_execution_evidence.py verify \
  --request .signalforge-data/handoff/requests/sf247-wsl-smoke-0001.json \
  --report .signalforge-data/handoff/reports/sf247-wsl-smoke-0001.json
git status --short
```

Do not commit the generated request/report, and do not copy other files from
`.signalforge-data/` into Google Drive.

## Google Drive: optional manual transport, real readback required

Existing private folders under **ChatGPT / SignalForge**:

- `00 Protocol & Templates`: protocol reference, not executable authority.
- `01 Execution Packages`: approved sanitized request JSON.
- `02 Execution Reports`: approved sanitized result JSON.

Verify actual folder identity and access before use; do not recreate folders or
change permissions.

For the real pilot:

1. Operator decides whether to use existing authenticated Drive sync/CLI or
   the browser. **No Drive CLI is assumed installed.**
2. Optionally upload only the allowlisted request JSON to `01 Execution Packages`;
   download it to WSL2, compare bytes/hash with the original, inspect and approve.
3. Perform the read-only local execution above.
4. Inspect the completed, sanitized report. Upload only this report JSON to
   `02 Execution Reports` via an authenticated account.
5. Record the **actual** Drive file ID returned by Drive.
6. Using ChatGPT's connected Google Drive, independently retrieve the uploaded
   report bytes (do not substitute the local file). Verify the request ID,
   revision, exit status, classification, canonical JSON report hash, and local
   report SHA against the value recorded before upload.
7. To verify independently *on WSL2*, download the uploaded report under a
   different temporary, ignored filename and invoke the `verify` command on it.
8. Record the sanitized result and actual verified Drive artifact identifier on
   PR/issue #247. Do not publish local personal pathnames or token URLs.

**An upload receipt is not a verified round trip.** The helper deliberately
reports `NOT_ATTEMPTED`; the GitHub acceptance note separately records
`VERIFIED` only after authenticated, independent readback and hash match.
A failed/missing/unauthorized Drive transfer is transport `FAILED` or
`NOT_ATTEMPTED`, not `VERIFIED`.

If the workstation cannot authenticate to Drive, use operator browser upload
of the sanitized JSON rather than installing a general-purpose Drive agent.
If genuine readback is unavailable, stop at `PARTIAL`, never `LOCAL_HANDOFF_READY`.

## Status and troubleshooting

- **LOCAL_HANDOFF_READY**: valid request, real WSL2 PASS, write-once and
  negative protections, actual authenticated Drive upload **and independent**
  retrieval with the same SHA-256, and sanitized GitHub evidence.
- **PARTIAL**: local execution verified but Drive round trip missing.
- **BLOCKED**: invalid checkout, unsafe request, failed smoke, corrupted report
  or other material integrity/safety failure.

Common causes:

- Wrong Python: activate the *existing* `.venv`; don't install into system Python.
- Wrong revision: use a new request ID after updating/checking out the intended
  commit; never silently substitute a new SHA.
- Existing report: preserve the first result, investigate and choose a **new**
  request ID for an intentional repeat.
- Git dirty: preserve changes, do not reset/clean them for convenience.
- Drive unavailable: retain the report locally; never paste raw logs or
  credentials into public GitHub comments.
- Interrupted upload: retry transport only after checking the exact remote
  artifact identity. Do not rerun the local execution or overwrite existing data.
- Hash mismatch: classify as BLOCKED/FAILED, preserve original artifacts,
  investigate differences; never edit the hashes to make them agree.

## Review and completion

Unit tests use a synthetic temporary Git repository; they are not proof of a
real workstation or Google Drive transfer. The operator and ChatGPT must
provide actual end-to-end evidence before declaring SF-247 ready.

Follow `docs/engineering-definition-of-done.md`, including focused tests,
Ruff, mypy, strict MkDocs, full pytest, PR adversarial review, review-thread
disposition and final-head CI. A green test suite alone is not sufficient.
The first PR must **not** be merged automatically.

No NSE strategy semantics, schema/migrations, canonical historical datasets,
data-source qualification or paper/live execution contracts change.
