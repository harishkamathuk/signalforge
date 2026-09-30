# Python Documentation Standard

SignalForge uses **Google-style Python docstrings** for source-level API documentation.

The aim is to preserve contracts, invariants and architectural intent close to the code without duplicating obvious implementation details.

## Required docstrings

Docstrings are required for:

- public modules;
- public classes, dataclasses, enums and protocols;
- public functions and methods;
- domain and persistence types with non-obvious semantic fields;
- strategy/runtime boundaries where ownership or ordering is part of the contract.

A public docstring should explain, where relevant:

- purpose and responsibility;
- important arguments and return values;
- contract-level exceptions;
- invariants, ordering or lifecycle assumptions;
- ownership boundaries, especially strategy versus shared runtime;
- side effects or persistence behaviour.

Use Google-style sections such as `Args:`, `Returns:`, `Raises:` and `Notes:` when they add useful information.

Private helpers do not require docstrings when their purpose is clear from the name, type signature and surrounding code. Add one when a helper has a non-obvious contract or invariant.

## Mandatory comments

Comments are mandatory when code contains an important reason that cannot be inferred safely from the implementation alone, including:

- ordering that affects trades, execution, recovery or auditability;
- guards that preserve strategy or lifecycle invariants;
- deliberate sequencing around persistence, idempotency or restart safety;
- workarounds for broker, exchange, database or library behaviour;
- non-obvious architectural boundaries;
- intentionally retained behaviour that could otherwise look redundant or removable.

Comments should explain **why**, not merely restate **what** the code does.

Prefer a rationale such as:

```python
# Reject non-positive risk before target tick lookup: rejected fills do not
# require target construction or a fill-date target rule.
```

Avoid comments that only paraphrase the following statement.

## Documentation discipline

- Do not duplicate normative strategy rules when the canonical strategy specification is authoritative; reference the relevant contract or ADR where useful.
- Do not use comments or docstrings to introduce or justify silent strategy changes.
- Update docstrings and comments in the same change that alters the documented contract.
- New or materially changed public code must meet this standard.
- Existing code should be brought up to the standard when it is materially modified; a full repository documentation rewrite is not a prerequisite for feature work.
