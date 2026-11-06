# ADR-011 — Proposed amendment: assumption-conditioned execution scenarios

**Status: PROPOSED, NOT ACCEPTED.** This file is a review artifact for
SF-254 / #254 under parent #253, *not* a change to the Accepted status or
requirements of [ADR-011](ADR-011-historical-execution-and-ambiguity-semantics.md).
No scenario price path, simulator, experiment or trade interpretation is
approved by creating, reviewing or merging a **draft** of this document.
The text below is a candidate addendum to ADR-011, to be accepted only
through parent Gate B and strategy/validation cross-contract approval.

## Proposed ADR-011 addendum text

### Separate scenario-conditioned historical research lane

ADR-011's bar-evidence model remains the authoritative strict historical
interpretation. Historical OHLCV proves reachability but not an arbitrary
intrabar event order. `FAIL_CLOSED_V1` and `BOUNDED_FLAT_V1` keep their
accepted meanings, outputs, execution-validity status and deterministic
identities. A scenario must not alter, replace, override, reinterpret or
resume a strict result implicitly.

A **distinct, opt-in research-only** historical execution-scenario calculation
may evaluate *if-then* consequences of an explicitly named, versioned
deterministic event-order assumption. Its price path is an invented,
declared **assumption**, never observed event chronology. It does not
synthesize provider ticks or historical timestamps or create authoritative
PAPER/LIVE Fill/Position/Trade/Exit facts. Any historical scenario result
is classified `SCENARIO_CONDITIONED`, `execution_valid=false` and
not eligible for strict determinate performance denominators, historical
trade claims, PAPER/live readiness or net-profitability conclusions.

A scenario input contract must carry separately typed, allowlisted fields
for (i) deterministic price-path rule/version, (ii) same-price event
tie/precedence, (iii) bar-open gap handling, (iv) in-bar time cutoffs,
(v) profile-based modeled fill application, and (vi) simulator calculation
version. Every rule must have an immutable semantic hash and validation
against approved combinations. No strategy-specific signal/entry/stop/
target formulas, arbitrary executable expressions, unversioned default
path or after-the-fact branch selection are permitted.

The scenario engine consumes existing strategy-owned completed-candle
decisions, `ArmIntent`, `ArmedPolicyIntent`,
`StrategyEntryFillView`, `post_fill_economics()` and shared
market/session policy. It observes only completed-candle decisions and
maintains one ARMED/OPEN state at a time for its conditional path. Reached
target is computed **after** the modeled entry fill from accepted strategy
economics, and slippage uses the explicitly selected predeclared
execution-assumption profile. An observed gap-through uses observed bar-open
evidence rather than silently filling at the trigger. UTC midnight is not
an exit. Unsupported crossing/tie/cutoff/gap cases, missing evidence,
non-positive risk, contradictory configuration, source corruption or
resource-budget exhaustion fail explicitly rather than choosing a
favorable/adverse outcome or resetting lifecycle state.

A scenario result must retain:

1. immutable audited dataset + provider/venue/instrument/traded-price basis,
   source-generation and content hashes, and covered source buckets;
2. strategy identity/version/config hash and indicator/engine calculation,
   measured window/pre-roll, session policy and source restrictions;
3. full scenario-assumption semantic mapping/id/version/hash,
   selected historical fill profile, tick-applicability status and new
   scenario-simulator calculation/version;
4. separate scenario-run, scenario opportunity and result identities,
   assumption-vs-observation causal trace, rejected/unresolved cases,
   modeled R and conditional OPEN/ARMED end state where applicable;
5. full source-to-result reproducibility and immutable, non-overwriting
   output location and hash.

A strict result and a scenario result must be impossible to confuse by
type, output label, filename/schema, mode identity or result namespace.
Conditional scenario metrics and their interpretation are owned by a
**separately preregistered and approved** validation contract; they may not
reuse SF-096's frozen `PASS_DIAGNOSTIC`, `FAIL_DIAGNOSTIC` or
`INCONCLUSIVE_DIAGNOSTIC` outcome codes. The original SF-096 result
and protected evidence stay immutable. General evidence-based OPEN-state
possible-worlds propagation remains separately deferred to #251;
scenario modelling does not claim exhaustive historical possibilities.

Before any implementation, the parent #253 must explicitly accept:
the selected first path rule(s), tie/cutoff/gap semantics, permitted
assumption combinations, strict separation and versioning contract,
sibling #255 research/metric interpretation and 01 strategy-owner
disposition. No behavior defaults may be inferred from a merely proposed
field name. The present directional approval is **contracts only**.

### Explicit non-goals / rejection

Reject implicit historical O-H-L-C or O-L-H-C traversal as **fact**;
choose-the-best-path optimization; favorable/adverse branch promotion;
fabricated ticks/time; mutable or overwriting strict research results;
current Delta tick normalization applied retrospectively; unqualified
source-to-execution-valid promotion; NSE or replay/PAPER/live semantic
changes; and a generic strategy DSL.

### Approval decision record — pending

| Decision | Proposed candidate | Current authority |
|---|---|---|
| Research-only, typed scenario lane | Separate runner/request/result and explicit mode | Direction for specification only (#253) |
| Single declared ordered OHLC path | Minimal candidate | **NOT APPROVED** |
| Specific high/low order | #255 proposes O-H-L-C under `BTC_OHLC_PATH_V1 / 0.1.0-proposal`, monotone segment crossings | **NOT APPROVED** |
| Ties and timed cutoffs | #255 proposes reject order-changing level ties; process final 1m Close before 5m validity expiry; unsupported in-minute cutoffs | **NOT APPROVED** |
| Gap/fill profiles | #255 proposes observed Open base followed by one RAW profile application and fill-based target | **NOT APPROVED** |
| Conditional output labels | `SCENARIO_CONDITIONED`/`SCENARIO_UNSUPPORTED`; separate `SCENARIO_METHOD_VALID/INVALID/INCONCLUSIVE` methodology labels | **NOT APPROVED** |
| New result namespace/provenance | Required | Proposed architecture, approval pending |
| Actual code/experiments | None | **NOT AUTHORIZED** |

**Rationale and examples:** see
[`execution-scenario-modelling-contract-proposal.md`](../execution-scenario-modelling-contract-proposal.md).
**Cross-review:** #255 (04 validation); 01 (strategy semantic owner); #253
(parent acceptance); accepted ADR-008/ADR-011 and SF-094 strategy/validation.

**Sibling cross-contract review (non-operative):** PR #257's corrected
`BTC_OHLC_PATH_V1 / 0.1.0-proposal` defines a candidate O-H-L-C monotone
hypothetical path, strict equal-level tie rejection, observed-bar-open gap
base, known end-of-5m expiry after final minute Close, and one-time raw
profile fill composition. These are representable by the proposed typed
boundary and are **not** accepted as market chronology, strategy rules or
executable scenario defaults. The proposed zero-unsupported completeness
criterion and methodology labels belong to #255; 01 semantic ownership
and #253 Gate B remain required before this draft becomes normative.
