# SignalForge — Agent Repository Instructions

These instructions apply to work in this repository using Codex, OpenCode or another coding agent. They are navigation and operating guidance, **not** an additional strategy specification, permission grant, review approval or merge authority.

## Sources and precedence

Before substantive work, inspect the current work item, repository state and applicable contracts. Use this precedence within each source's domain:

1. Approved, versioned normative strategy specifications and applicable [architecture decisions](docs/architecture/decisions/).
2. Current [Engineering Definition of Done](docs/engineering-definition-of-done.md), engineering standards and issue-specific acceptance criteria.
3. Versioned source/tests, accepted GitHub decisions, PR review evidence and CI for the exact relevant revision.
4. Project Sources provide persistent navigation/context but do not override GitHub authority.
5. Conversation recollection is lowest precedence and cannot override the sources above.

Start with [README](README.md), the [PR template](.github/pull_request_template.md) and the [Python Documentation Standard](docs/python-documentation-standard.md). Follow applicable ADRs, normative specifications and issue contracts rather than reproducing them here. An ADR's historical-reference status or supersession matters; do not treat an older reference as overriding a later accepted contract. If authorities conflict, stop and surface the conflict.

## Strategy, architecture and evidence boundaries

- Make strategy rules explicit and approved before implementation. Never silently change signals, entry, stops, targets, sizing, validity, exits, lifecycle semantics or resulting trades.
- Preserve deterministic completed-candle ordering, no look-ahead, typed contracts, exact provenance and compatible replay/research/paper/live semantics wherever applicable.
- Follow [ADR-008](docs/architecture/decisions/ADR-008-strategy-runtime-boundary.md): concrete strategies own policy; shared runtime owns lifecycle mechanics, authoritative execution facts and persistence; market-data and broker integrations belong behind adapters.
- Preserve state ownership, idempotency, restart/recovery, auditability and fail-closed treatment of contradictory or missing evidence. Follow applicable persistence and execution ADRs.
- Follow [ADR-011](docs/architecture/decisions/ADR-011-historical-execution-and-ambiguity-semantics.md) and accepted research contracts: distinguish observed market facts, modeled assumptions, ambiguity and qualified evidence. Never present provisional data, hypothetical fills or unvalidated P&L as execution-valid results.
- Prefer small, modular, tested changes and maintained repeatable workflows. No speculative frameworks, services or agent infrastructure.

## Work commands and permissions

Commands are case-insensitive and context-aware: an explicit issue/PR target overrides the inferred active work item. Approved issue scope and current GitHub contracts remain authoritative; the Project Working Protocol provides additional context when available:

- **PRM / REC / HOF:** Produce a copy-ready implementation prompt / recommendation / source-grounded handover, respectively; do not implement.
- **IMP:** Implement accepted scope, test, document, perform adversarial review and prepare/update the PR. **Do not merge.**
- **REV:** Adversarial, evidence-based review of current contracts, changes and tests. **Do not modify files or GitHub state.**
- **COR:** Independently verify findings, make narrow approved-scope fixes, add relevant regression tests, rerun applicable checks and record review-thread dispositions. Escalate material changes before implementation.
- **FIN:** Only after an explicit owner request, verify the exact PR head, issue acceptance, review threads, independent-review provenance and final required CI; merge an eligible PR using the prescribed merge-commit method, then verify merge and perform safe housekeeping.

Routine implementation choices and valid bounded corrections need no repeated owner approval. **Stop for explicit approval before** materially changing strategy/trades, capital exposure or execution correctness, durable-state integrity, restart/recovery, auditability/reproducibility, or destructive/substantially hard-to-reverse architecture, API or schema contracts. Record material decisions in authoritative Git artefacts.

These instructions never grant shell, filesystem, GitHub-write, deployment, protected-data or automatic-merge permissions. Observe the actual tool and environment restrictions and specific work-item authorisations.

## Tests, review and completion

- Follow the [DoD](docs/engineering-definition-of-done.md) and [PR template](.github/pull_request_template.md), including focused and negative/boundary tests, documentation, and applicable strategy-abstraction, persistence/migration and deterministic replay/golden proof.
- Run or verify the applicable standard gates: `ruff check .`, `mypy signalforge`, `mkdocs build --strict`, `pytest -s`, `git diff --check`. Record exact outcomes and explain genuinely inapplicable checks; never invent test, CI, or readiness evidence.
- Inspect **all** relevant human and automated/third-party PR review threads. Verify each actionable finding against current code and contracts; retain evidence-backed dispositions and independently verified thread resolution.
- An author-assisted critical review or agent self-review is **not** independent third-party approval. Green CI alone does not satisfy the adversarial-review requirements. Revalidate after the latest review-driven changes against the **current PR head**.
- Normal PRs target `develop` and use GitHub's **Create a merge commit** method unless an owner-approved exception is recorded. Only explicit **FIN** after all applicable gates may merge. Do not write directly to `develop` or enable auto-merge.
