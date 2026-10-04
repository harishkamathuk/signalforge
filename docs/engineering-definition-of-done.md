# Engineering Definition of Done

This document defines the cross-cutting completion criteria for SignalForge implementation work.

Issue-specific acceptance criteria remain authoritative for the work item. This Definition of Done applies in addition to them unless a requirement is explicitly documented as not applicable.

## Before implementation

- Read the applicable ADRs, normative strategy specifications and engineering standards.
- Identify whether the change affects strategy semantics, public APIs, lifecycle ordering, persistence, recovery, idempotency, auditability, generated documentation or schema.
- Do not silently reinterpret strategy behaviour or durable-state contracts.
- Escalate only when implementation evidence reveals a material decision affecting trades, capital exposure, durable state, recovery/auditability, or destructive/hard-to-reverse API/schema change.

## During implementation

- Keep strategy policy separate from shared runtime, persistence and broker/data adapters.
- Preserve deterministic completed-candle ordering and avoid look-ahead.
- Preserve authoritative state ownership and idempotency requirements.
- New or materially changed public Python code must comply with the [Python Documentation Standard](python-documentation-standard.md).
- Add mandatory rationale comments for non-obvious ordering, invariants, lifecycle safety, persistence/recovery sequencing and external-system constraints.
- Update generated API documentation pages when a new public API surface should be discoverable.
- Keep code, domain validation and persistence constraints mutually consistent.
- Add or update tests for changed contracts, including negative/contradictory cases where relevant.

## Adversarial review before merge

Every implementation PR must receive a cross-cutting adversarial review in addition to normal acceptance testing.

Review specifically for:

- strategy-semantic leakage into shared runtime;
- unapproved signal/entry/stop/target/validity/exit changes;
- domain versus persistence invariant mismatches;
- lifecycle/state-transition ordering regressions;
- restart/recovery inconsistencies;
- idempotency/retry weaknesses;
- stale/missing/corrupt state being guessed rather than rejected;
- session/execution safety gaps;
- look-ahead or ambiguous completed-candle behaviour;
- undocumented public contracts;
- missing rationale comments around non-obvious invariants;
- generated API documentation becoming stale or incomplete;
- accidental scope expansion into later milestones.

A green test suite is necessary but is not by itself sufficient evidence of completion.

### Boundary and determinism review

When a change introduces or materially changes a serialization, configuration, persistence,
market-data, broker/API, identity/hash, timestamp/timezone, numeric, or filesystem/data-source
boundary, explicitly ask:

> What information can be lost, changed, collapsed, reordered or interpreted differently as data
> crosses this boundary?

Review the applicable boundary for:

- precision loss;
- canonicalization differences;
- round-trip fidelity;
- deterministic ordering;
- timezone normalization;
- duplicate or ambiguous values;
- large/small magnitude boundaries;
- invalid-but-parseable inputs;
- identity collisions;
- ambient/global-context sensitivity.

This is a conditional review discipline, not an additional approval gate. Apply only the checks
that are relevant to the changed boundary. If no new or materially changed boundary exists, state
that explicitly rather than manufacturing irrelevant checks.

When a material boundary invariant is identified, prefer focused regression evidence that proves
the invariant directly. The durable protection should be the executable contract, not reviewer or
author memory.

### Pull-request review-thread discipline

Before merge, inspect all pull-request review conversations, including human reviewers and
automated/third-party reviewers such as Devin. Reviewer output is advisory evidence, not an
authority: independently verify each finding against the current code, accepted specifications,
ADRs and tests.

For every actionable review-thread finding:

- determine whether the finding is valid and material;
- correct the implementation when required and add regression evidence where appropriate;
- reply in the review thread with the disposition and concrete evidence;
- resolve the thread only after the correction/disposition has been independently verified.

If a finding is rejected or is no longer applicable, reply with the technical rationale and
supporting evidence before resolving it. Do not resolve a thread merely because CI is green or
because an automated reviewer reports success.

Before merge, confirm that:

- no material review thread remains unresolved;
- material third-party review findings are reflected in the PR adversarial-review record;
- the final required CI/validation run is green after the latest review-driven code or
  documentation change.

## Recording findings

Material findings must not remain only in chat.

Classify and retain them as follows:

- **Durable architecture rule or clarification** — update the applicable ADR or create a new ADR only when warranted.
- **Implementation/review evidence** — retain the finding, risk, correction and validation evidence in the PR.
- **Local invariant or ordering rationale** — encode it in source comments/docstrings and tests.
- **Normative strategy change** — do not implement silently; route it through the strategy-definition authority and versioning process.

Resolved review findings should remain visible in the PR history or summary so future maintainers can understand why the final shape exists.

## Required validation

For Python implementation work, run the applicable repository gates:

```bash
ruff check .
mypy signalforge
mkdocs build --strict
pytest -s
git diff --check
```

Also run:

- focused unit/integration tests before the full suite;
- Alembic/current-head checks when persistence or schema is involved;
- migration upgrade/downgrade checks when a migration is added;
- deterministic replay/golden tests when runtime or strategy behaviour is affected.

If a standard gate is genuinely not applicable, state why in the PR.

## Pull request evidence

The PR must state:

- issue/work item and applicable architecture/specification authority;
- scope and explicit non-goals;
- whether strategy semantics changed;
- whether schema/migrations changed;
- documentation/API impact;
- adversarial findings and their disposition;
- focused and full validation results;
- any unresolved blocker or required follow-up.

## Completion rule

A work item is complete only when:

1. issue-specific acceptance criteria are met;
2. strategy semantics remain accepted and explicit;
3. code, tests, persistence/recovery behaviour and documentation agree;
4. material adversarial findings are resolved and durably recorded;
5. required quality gates pass;
6. the PR contains sufficient evidence to reproduce why the implementation was accepted.
