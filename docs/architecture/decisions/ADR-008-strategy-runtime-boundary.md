# ADR-008 — Strategy Runtime Boundary

**Status:** Accepted  
**Decision source:** SF-060 / GitHub #138  
**Applies from:** SF-061 onward

## Context

SignalForge's first deterministic vertical slice was implemented around `intraday_momentum_v1 / 1.0.0`. That proved the end-to-end runtime, but several shared seams became shaped around Strategy V1 policy, including its Trend/Momentum/Setup decomposition, fixed indicator composition, entry-trigger offset, pre-entry invalidation, and 1.5R target economics.

SignalForge now needs to host materially different strategies without rewriting replay orchestration, lifecycle mechanics, persistence/recovery patterns, or broker/data adapters, and without turning configuration into an executable strategy language.

## Decision

Adopt a **stable engine + strategy code** architecture.

The reusable runtime depends on a small typed `Strategy` contract at genuine lifecycle boundaries. Concrete trading policy remains in Python strategy implementations.

The strategy boundary covers:

1. completed-candle evaluation;
2. ARMED-event policy;
3. post-fill position economics.

Trend/Momentum/Setup are Strategy V1 implementation details, not universal framework abstractions.

## Stable engine responsibilities

SignalForge core owns:

- deterministic market-event and completed-candle ordering;
- canonical candle construction and market/runtime facts;
- canonical indicator implementations and checkpoint mechanics;
- NSE tick-size/reference primitives and tradable-price normalization;
- TriggerEvent, EntryIntent and authoritative Fill creation;
- ARMED/TRIGGERED/EXPIRED and OPEN/CLOSED lifecycle mechanics;
- execution coordination;
- Trade, Position and Exit as authoritative persisted facts;
- transactional persistence, idempotency, audit transitions and restart validation;
- explicit intraday session-safety constraints.

A strategy must not manufacture authoritative execution facts or mutate durable lifecycle state directly.

Strategy-facing lifecycle state must therefore be exposed through read-only facts/views. Strategy code emits typed decisions/intents; only shared lifecycle mechanism is allowed to perform lifecycle state transitions.

Compulsory intraday/session safety is a shared runtime guardrail and cannot be weakened or bypassed by strategy policy. A strategy may impose an earlier or stricter entry cutoff, but not a later one that would violate the shared safety boundary.

## Strategy responsibilities

A concrete strategy owns:

- strategy identity/version and typed configuration;
- canonical semantic configuration mapping;
- declared indicator requirements;
- qualification and diagnostic/rejection logic;
- raw entry-trigger policy;
- opportunity validity;
- strategy-specific pre-entry invalidation;
- initial stop selection;
- post-fill target/economic policy;
- strategy-specific mutable state only when a real strategy requires it.

For Strategy V1 this includes the existing EMA/RSI/ADX qualification rules, diagnostic MACD use, `1.001` raw trigger, signal-low pre-entry invalidation, signal-low stop, immediately-following-candle validity, and actual-fill-based `1.5R` raw target.

Strategies provide raw economic intent. Conversion from raw prices to valid tradable exchange prices remains a shared engine responsibility using the accepted NSE tick-size rules. Concrete strategy code must not own exchange tick normalization.

## Trade economics

Actual Fill remains authoritative and outside strategy control.

`Trade` remains the authoritative economic fact but must not enforce Strategy V1's `1.5R` target formula as a generic domain invariant. The strategy supplies accepted stop/raw-target economics; the shared runtime validates generic invariants, performs required tradable-price normalization, and persists the resulting Trade/Position facts.

Generic domain validation and durable persistence constraints must remain consistent. Removing a Strategy V1-specific formula does not imply relaxing unrelated strategy-neutral invariants already required by durable storage. For the current long-only model, accepted raw targets must remain above entry unless a future explicitly accepted domain/schema change says otherwise.

For long entries, non-positive risk is rejected before target construction or target tick-size resolution. A rejected Fill must not require target generation or a fill-date target tick rule merely to determine that no position can be opened.

## Indicator composition

EMA, RSI, ADX and MACD implementations remain shared canonical primitives.

Each strategy declares only the known typed indicators it requires. Indicator readiness is requirement-specific rather than defined by a fixed Strategy V1 snapshot.

The accepted numerical contracts, seeding, readiness, recursion, precision and completed-candle semantics of existing indicators must not change as part of this extraction.

## Configuration and strategy resolution

Configuration selects and parameterises known typed Python strategy implementations.

Use an explicit in-process registry keyed by strategy ID and version. Preserve the existing shared configuration-identity/hashing mechanism and Strategy V1 semantic mapping so extraction does not silently alter accepted V1 config hashes or deterministic run identity.

Do not introduce:

- a strategy DSL;
- executable YAML;
- `eval`;
- dynamic imports or module paths in configuration;
- package/plugin discovery;
- a generic expression/DAG workflow engine;
- a mandatory EntryPolicy/StopPolicy/TargetPolicy hierarchy.

## Persistence and recovery

Existing run provenance and Signal/Fill/Trade/Position/Exit relationships remain substantially valid.

Two persistence areas require generalisation:

- strategy-evaluation persistence must stop requiring Strategy V1 Trend/Momentum/Setup fields;
- indicator-checkpoint persistence must become self-describing for the strategy's declared indicator set.

Recovery remains shared. Startup supplies typed strategy configuration, persisted provenance verifies it, and indicator/checkpoint compatibility is validated explicitly. Recovery must not infer strategy identity from stored indicator shape.

## Consequences

The implementation sequence is:

- **SF-061:** extract the Strategy contract and make replay orchestration strategy-agnostic;
- **SF-062:** separate strategy policy from lifecycle intents/economics and remove the generic 1.5R Trade assumption;
- **SF-063:** generalise indicator requirements, state and checkpoint persistence;
- **SF-064:** add explicit strategy registry and typed config resolution;
- **SF-065:** implement the RSI mean-reversion reference strategy;
- **SF-066:** prove cross-strategy replay, persistence and Strategy V1 non-regression.

SF-062 established the following implementation clarifications for ADR-008:

- strategy lifecycle inputs are read-only views/facts, not mutable lifecycle entities;
- strategies emit raw trigger/stop/target intent, while shared core owns exchange tick normalization;
- compulsory intraday session safety remains shared and non-overridable, while strategy-specific entry cutoffs may be stricter;
- generic economic validation must remain aligned with durable persistence constraints;
- non-positive-risk rejection precedes target construction/normalization.

No Strategy V1 signal, entry, stop, target, validity, exit, session-timing, or indicator numerical semantics are changed by ADR-008.

## ADR source-of-truth convention

Git is canonical for SignalForge architecture decision records from ADR-008 onward.

ADR-001 through ADR-007 predate the repository's standalone ADR-file convention. A later concrete historical-recovery need resulted in retrospective reference ADR files being reconstructed from the contemporaneous 02.01 Strategy Framework & Architecture conversation. Those files are explicitly historical references only; they do not become part of the Git-native ADR series and must not override ADR-008 or later accepted decisions, current strategy specifications, implementation contracts or tested system behaviour.

GitHub issues and pull requests retain discussion, implementation scope and evidence. Google Drive governance and architecture material may summarize or point to ADRs, but must not become an independently maintained competing ADR source of truth.
