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
for (i) deterministic price-path, (ii) same-price event
tie/precedence, (iii) bar-open gap handling, (iv) in-bar time cutoffs,
and (v) modeled fill application, each as an **explicit immutable
`(id, version)` pair**, plus the scenario ID/version and simulator
calculation version. The `_V1` suffix of an ID is not a version.
The canonical assumption semantic hash must bind all five full pairs,
all numeric settings and the approved registry mappings; changing
semantics requires a new version and cannot retain the old hash.
No default/inferred version or rule is permitted. #255's current
O-H-L-C candidate supplies the price rule/version but has not yet
registered explicit versions for its four other `_V1` subpolicy IDs;
the architecture proposes `1.0.0-proposal` for each **subject to sibling
reconciliation**, not as accepted assumptions. No strategy-specific signal/entry/stop/
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

A scenario result must retain and bind to a **versioned canonical
execution manifest** before processing:

1. a `SCENARIO_RESEARCH` namespace/schema; audited dataset identity,
   provider/venue/instrument/traded-price basis, generation/audit ID,
   source content hash, complete source interval, 1m/5m coverage and
   aggregation/decision-data calculation identity;
2. strategy **ID and version**, config **ID and hash**, indicator engine
   calculation **ID and version**, UTC measured IS/OOS and pre-roll
   boundaries, and market/session policy **ID and version**;
3. scenario **ID and version**, all five explicit subpolicy **IDs and
   versions**, numeric settings and full assumption-semantic hash;
   the selected RAW fill profile **ID/version and complete semantics**,
   price mode, unresolved tick-applicability marker and scenario
   simulator calculation **ID/version**;
4. finite, explicit resource limits for state/transition/event/evidence
   volume, a versioned **resource-budget policy ID/semantic hash**, and
   fail-closed exhaustion behavior; the actual repository/calculation
   revision and canonical serializer version;
5. distinct planned `scenario_run_id` and produced `scenario_result_id`,
   scenario opportunity identities, assumption-vs-observation trace,
   rejected/unsupported cases, conditioned modeled R and preserved
   conditional OPEN/ARMED terminal state; protected, non-overwriting
   output location and canonical evidence hash.

Define `scenario_run_id` as a domain-separated hash over the **complete
canonical pre-run manifest**, explicitly including resource policy,
strategy version, source identity, profile semantics and windows. A
changed budget or model/version must change the run identity even if
nothing else changes. The result ID is separately derived from the
run ID, canonical output evidence digest, completion/termination state
and failure boundary, with **no output digest included in the run-ID
preimage**. At budget exhaustion the record must preserve input/run
identity, all budget limits, attempted count, last complete/failing
source boundary, pre-failure causal state IDs, reason and explicit
unsupported/terminated status. It cannot quietly return or prune a
partial economically selective history. Later engineering tests must
prove byte-identical reruns, cross-mode collisions impossible, and
budget variations produce distinct identities.

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

**COR #256 — review M1/M2 (non-operative):** The typed architecture now
requires explicit `(id, version)` pairs for each of five scenario
subpolicies and proposes `1.0.0-proposal` for the four suffix-only
rules in #255, subject to that sibling's written reconciliation. The
separate canonical pre-run manifest fully binds strategy/config,
source/data, assumption/profile, session/window, simulator and finite
resource-budget policy; result identity and exhaust provenance are
separate. None of these identity-format corrections grants permission
to run O-H-L-C or accept the scenario methodology. Parent #253 Gate B
and the strategy-owner/sibling prerequisites remain authoritative.
