# SF-254 — Historical execution scenario architecture (proposed contract)

**Status:** PROPOSED / SPECIFICATION ONLY — no implementation or execution authority.
**Owner:** 02 — Strategy Framework & Architecture.
**Parent:** [#253](https://github.com/harishkamathuk/signalforge/issues/253).
**Validation counterpart:** [#255](https://github.com/harishkamathuk/signalforge/issues/255).
**Normative amendment candidate:** [ADR-011 scenario proposal](decisions/ADR-011-scenario-execution-proposed-amendment.md).
**Decision gate:** Parent #253 has approved the specific scenario-assumption selection for specification finalisation (owner decision [#6694636203](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6694636203)); final normative Gate B acceptance, independent review and PR merge remain pending.

## 1. Decision boundary

The approved decision is to **specify** a separate research-only deterministic
execution-scenario model. It is **not** an approval of a price traversal rule,
fill, implementation, simulation, strategy-performance interpretation, or a
change to existing accepted historical evidence. #253 identifies a first
increment consisting of one declared deterministic OHLC path as a **candidate**.
The owner has since approved the concrete #255 assumption set for
**specification finalisation only**, not as operative chronology or final
normative Gate B acceptance. The remaining review/merge and research
preregistration gates below still apply.

### Source-grounded constraints

- Accepted ADR-011 states that an observed 1-minute OHLCV range proves reach,
  not intrabar event order; it expressly rejects an assumed OHLC traversal
  **as a canonical historical result**.
- ADR-008 separates strategy-owned completed-candle decisions, ARMED intent
  and post-fill economics from shared lifecycle mechanics. Scenario assumptions
  may choose only hypothetical event order/fill interpretation, never strategy
  qualification, entry, invalidation, stop, target or validity.
- The current `historical_execution.py` implements strict
  `FAIL_CLOSED_V1` and opt-in `BOUNDED_FLAT_V1` for `RAW_DIAGNOSTIC`.
  Its ambiguity enums include `ENTRY_VS_POST_FILL_TARGET`,
  `ENTRY_VS_INVALIDATION`, `ENTRY_VS_POST_FILL_STOP`,
  `STOP_VS_TARGET`, and time-cutoff ambiguity.
- Frozen `btc_momentum_baseline_v0 / 0.1.0-experimental` is long only,
  completed 5m decisions, continuous UTC; source prices are traded-price
  observations. The frozen SF-094 Tier-1 experiment uses SF-088
  `generation-0001`, fixed IS/OOS, `REFERENCE_RAW / 1.0.0` and
  `ADVERSE_RAW / 1.0.0`, `execution_valid=false`. Original SF-096
  strict/v2 evidence remains immutable and `INCONCLUSIVE_DIAGNOSTIC`.

### Non-equivalent evidence categories

| Category | Meaning | Permitted presentation |
|---|---|---|
| `OBSERVED_SOURCE` | Actual canonical 1m OHLCV and UTC boundaries | Source fact, with audit identity |
| `STRICT_INFERABLE` | Invariant reachability/lifecycle conclusion from accepted ADR-011/BOUNDED_FLAT semantics | Evidence-inferable; strict result only |
| `STRICT_AMBIGUOUS` | Multiple OHLCV-compatible outcomes; possibly OPEN | Bounded possibilities, not a chosen trade |
| `SCENARIO_CONDITIONED` | Outcome under explicitly declared path and fill assumptions | Assumption-conditioned only; never observed or strictly determinate |
| `SCENARIO_UNSUPPORTED` | Scenario cannot define a complete, consistent outcome | Explicit failure/uncertainty, no silent fallback |
| `SOURCE_UNQUALIFIED` | Provider/tick/contract qualification unresolved | `execution_valid=false` and precise limitation |

An observed OHLCV value may be reused by a scenario; the scenario's event
sequence does **not** thereby become observed. A scenario result must not use
strict `DETERMINATE` alone as its certainty label.

## 2. Minimal typed architecture

Propose **two independent dispatch paths**, selected explicitly before
processing input. This is a design contract, not a Python API or an implemented
configuration shape.

### Existing strict lane — unchanged

`HistoricalBarExecutionRunner.run(..., continuation_policy=FAIL_CLOSED_V1)`
remains the default. `BOUNDED_FLAT_V1` stays a separately opt-in strict
research inference. No scenario settings are accepted by these calls; no
implicit scenario fallback after strict termination. Existing NSE
`EXECUTION_VALID`, paper/live, RunIdentity, signal/result hashes and
ambiguity reports must remain byte-identical for the same inputs.

### Proposed scenario lane — assumption selection approved for specification finalisation, **not operative**

`ScenarioResearchRunner.run(ScenarioResearchRequest)` (conceptual name only)
accepts a **prevalidated** dataset + audit proof, the existing
`StrategySelection`/config and typed strategy boundary, an explicit
`ScenarioAssumptionSet`, an existing explicitly named
`HistoricalExecutionAssumptionProfile`, market/session policy and a
measurement/pre-roll boundary. No scenario request can cause any broker action
or create authoritative `domain.execution.Fill`, Trade, Position or Exit.

Proposed immutable typed fields:

| Type | Required field(s) | Validation |
|---|---|---|
| `ScenarioAssumptionSet` | `scenario_id`, `scenario_version`, and **explicit `(id, version)` pairs** for `price_path_rule`, `event_tie_policy`, `gap_policy`, `time_boundary_policy`, and `fill_application_policy` | Exact registered immutable IDs and versions; reject missing, unapproved, conflicting or unknown combinations |
| `ScenarioResearchRequest` | `mode=SCENARIO_RESEARCH`, source dataset/audit, strategy selection/config, explicit assumption set, frozen execution profile, simulator calculation version, measured boundaries | Strongly typed; no coercion from strict results; no external-data substitution |
| `ScenarioObservationTrace` | 1m source bucket, observed O/H/L/C, path assumption/ordered *hypothetical* probes, causal strategy intent/guard, modeled fill/economics, assumption vs observation tags | Each invented step marked `ASSUMED`; no fake provider timestamp/tick ID |
| `ScenarioLifecycleOutcome` | unique scenario run + opportunity IDs, terminal or OPEN/ARMED/unresolved state, conditional exit/reason/R, source-bar refs, assumption IDs, flags | Always `SCENARIO_CONDITIONED` or explicitly unsupported |
| `ScenarioResearchResult` | provenance, complete/terminated flag, coverage, unsupported counts, conditional metrics, strict-reference IDs (comparison only), `execution_valid=false` | Never interchangeable with strict `HistoricalExecutionRunResult` |

#### Canonical subpolicy identity — M1 contract correction

Each of the five subpolicies is a **separate immutable structured pair**
`{id: nonempty_str, version: nonempty_str}`, not a string with an inferred
suffix. The full `ScenarioAssumptionSet` contains its own explicit
`scenario_id` and `scenario_version` plus the five pairs and any
declared numeric parameters. Versions are exact registered strings; a
`_V1` suffix in an ID is **not** a version. Canonical serialization uses
fixed field names, sorted keys, exact decimal strings and UTC-aware
timestamps. Both the scenario version and **all five subpolicy IDs and
versions** enter the assumption semantic hash. The versioned registry
maps each pair to fixed semantics; changing any rule definition, tie,
gap, cutoff, fill composition or numeric parameter requires a new
version and semantic hash. Unknown or duplicate/conflicting
registrations are invalid, not a reason to select a default.

For cross-contract alignment, the **owner-selected, still non-operative** #255 first scenario
`BTC_OHLC_PATH_V1 / 0.1.0-proposal` maps to:

| Subpolicy | Proposed ID | Proposed explicit version |
|---|---|---|
| Price path | `OPEN_HIGH_LOW_CLOSE` | `1.0.0-proposal` |
| Event ties | `REJECT_SAME_LEVEL_TIE_V1` | `1.0.0-proposal` |
| Gap | `OBSERVED_OPEN_FIRST_V1` | `1.0.0-proposal` |
| Time boundary | `FIVE_MINUTE_EXPIRY_AFTER_FINAL_CLOSE_V1` | `1.0.0-proposal` |
| Fill application | `RAW_PROFILE_AFTER_BASE_V1` | `1.0.0-proposal` |

These five explicit `(id, version)` mappings are now **reconciled** with
#255's corrected PR #257 at head
`1ba45856bc4598d80c4e02bfe1776139bbe13713`.
The parent #253 owner has **approved these exact assumption identities for
specification finalisation only**. The resulting contract is still
**PROPOSED / NOT OPERATIVE**; `_V1` never substitutes for an explicit
version. This reconciliation and selection do not establish O→H→L→C as
observed chronology or authorize scenario execution.

The modeling layer consumes the **same strategy-owned** `ArmIntent`,
`ArmedPolicyIntent`, `StrategyEntryFillView` and
`post_fill_economics()` as accepted historical machinery. It must not contain
BTC-specific EMA/RSI/ADX qualification, trigger formulas or stop/target
formulas. Shared generic code may be factored *only after* implementation
approval and cross-strategy tests under ADR-008. Scenario configuration is an
allowlisted, versioned set of known assumptions, **not a strategy DSL**.

### Ownership of assumptions and ordering

1. Canonical 1m bar **open occurs first** and close last; H/L ordering within
   the minute is **unobserved**. If a path rule is explicitly approved, it
   emits *hypothetical level visits*, not actual trades, ticks or timestamps.
2. Strategy decisions are computed only on completed 5m candles. A scenario
   cannot signal earlier or consume forming candles. ARMED and OPEN policy
   comes from existing typed strategy intent and session policy.
3. **Owner-selected first scenario for specification finalisation:**
   `BTC_OHLC_PATH_V1 / 0.1.0-proposal` fixes the hypothetical one-minute
   **Open → High → Low → Close** sequence with continuous monotone
   level-order traversal and first crossings. This selection is recorded
   on parent #253 (owner decision #6694636203), **not** inferred by the
   engine from outcome, strategy direction, future profit or volatility.
   It remains **non-operative pending final normative Gate B acceptance**;
   an O-L-H-C alternative would require a different registered scenario
   and new approval, not an execution-time choice.
4. Exact ordering of an entry trigger, pre-entry invalidation, stop, target,
   cutoff and expiry is evaluated by walking the hypothetical path and known
   UTC time boundaries **without fabricating exchange event timestamps**.
   If order relative to an in-minute time cutoff is not specified by an
   accepted `time_boundary_policy_id`, return `SCENARIO_UNSUPPORTED`.
5. An already-reached bar-open trigger/stop/target uses the observed opening
   price as the modeled base where the accepted strict model requires it.
   Never use an invented better trigger-price fill for a gap. If a modeled
   entry is invalid (non-positive risk), reject through accepted domain rules.
6. Immediately after a *modeled* entry, call strategy post-fill economics
   with the selected profile-adjusted modeled entry fill. Resolve the target
   from that fill, not from an arbitrary before-entry target. Apply the
   predeclared `REFERENCE_RAW` or `ADVERSE_RAW` slippage to modeled entry,
   stop and target exit consistently; do **not** normalize using an
   unsupported current Delta historical tick size.
7. Apply one active ARMED/OPEN lifecycle per scenario run. If a path remains
   OPEN across bars, carry that conditional state forward. No forced UTC
   midnight close. At dataset end mark the conditional OPEN/ARMED state
   unresolved; never invent an exit.
8. If the scenario describes unphysical levels or inconsistent OHLCV
   (non-positive bars, O/C outside [L,H], H < L), invalid time assumptions,
   contradictory policy, unavailable source/audit, unknown rule, unsupported
   event tie or budget exhaustion, **reject or terminate** with an explicit
   reason; never recover by choosing a favorable/adverse path.

### Sibling #255 concrete scenario — reviewed; owner-selected for specification finalisation, NOT operative

The corrected sibling validation draft in [PR #257](https://github.com/harishkamathuk/signalforge/pull/257),
head `1ba45856bc4598d80c4e02bfe1776139bbe13713`, proposes the
**single** assumption set `BTC_OHLC_PATH_V1 / 0.1.0-proposal`.
It is architecturally representable within the typed, allowlisted
scenario lane. Its material assumptions are **approved for specification
finalisation** by #253, but it is **not observed history, a finally
accepted normative contract or an operative scenario configuration**:

| Boundary | #255 proposed rule | #254 architecture disposition |
|---|---|---|
| Hypothetical 1m price sequence | Open → High → Low → Close; continuous monotone level traversal per segment | Compatible *as a declared assumption*, never observed chronology |
| Event ties | Order-changing equal-level ties become `SCENARIO_UNSUPPORTED` | Compatible; no favorable/adverse default |
| Gap base | Actual observed bar Open, then named profile exactly once | Compatible; retain strict bar-open price precedence |
| Validity end | Process final 1m constituent bar through Close, expire at known 5m boundary | Compatible for the **frozen BTC validity**; no general rule for intraminute time cutoffs |
| In-minute cutoff | Unsupported without an explicit approved time rule | Compatible fail-closed behavior |
| Modeled entry economics | Fill base first; apply REFERENCE_RAW or ADVERSE_RAW once; derive post-fill target from resulting entry | Compatible with typed `post_fill_economics()` boundary; no second gap slippage |
| Sample and methodology | 288 warm-up; 69,984 IS + 34,848 OOS decision candles; zero measured `SCENARIO_UNSUPPORTED` for point estimates | No architectural conflict; research methodology/interpretation owned by #255 |
| Result labels | `SCENARIO_METHOD_VALID / INVALID / INCONCLUSIVE` | Distinct from strict SF-096 labels; methodology disposition must remain separate from economic performance |

**Owner decision recorded:** parent #253 [#6694636203](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6694636203)
**approved the specific path, monotone ordering, tie/expiry/gap/fill
assumptions, full-grid/zero-unsupported threshold and distinct method
labels for specification finalisation**. Strategy owner 01 recorded
`STRATEGY_SEMANTICS_UNCHANGED`. **Final normative Gate B acceptance,
required independent review or documented DoD disposition, and merge
remain pending**; neither selected assumptions nor the strategy-owner
review authorize implementation or experiments. Strict ambiguity stays
unchanged by any scenario outcome.

**Research method clarification:** zero `SCENARIO_UNSUPPORTED` is the
validation sibling's predeclared completeness threshold; the architecture
must still support recording positive unsupported counts without hiding them.
A retained conditional OPEN/ARMED state at the dataset end is **not** a
fabricated closure; #255 explicitly permits lifecycle-coverage completion
without counting that state as a closed trade.

### Event ties, gaps and cutoffs — selected for specification finalisation, NOT operative

For the owner-selected `BTC_OHLC_PATH_V1 / 0.1.0-proposal`, the
explicit `REJECT_SAME_LEVEL_TIE_V1 / 1.0.0-proposal` policy classifies
same-level ties that change lifecycle order/economics as
`SCENARIO_UNSUPPORTED`; it does **not** introduce universal favorable or
adverse precedence. The selected `OBSERVED_OPEN_FIRST_V1 /
1.0.0-proposal` policy uses the **observed one-minute Open as modeled
gap-fill base**, subject to scenario trigger reachability, rather than
inventing an improved barrier-price fill. The selected
`FIVE_MINUTE_EXPIRY_AFTER_FINAL_CLOSE_V1 / 1.0.0-proposal` policy
processes the final constituent minute through Close before the known
five-minute validity expiry; an unknown in-minute cutoff is still
`SCENARIO_UNSUPPORTED`, with no fabricated fractional timestamp.
`RAW_PROFILE_AFTER_BASE_V1 / 1.0.0-proposal` applies the predeclared RAW
profile once after determining the path/gap base, and retains the
strategy-owned post-fill target rule.

These **specific rules are reconciled with #255 and approved by parent
#253 for specification finalisation only**, not as observed history or
operative execution defaults. Final normative Gate B acceptance,
required review/DoD evidence and merge remain pending; implementation
must not infer any unregistered tie, gap, cutoff or fill rule.

### Research-only safety separation

There is no implicit API flag to turn a strict result into scenario truth,
no fallback on `OPEN_POSSIBLE`, and no reuse of authoritative fill/trade
persistence. A future CLI, **if explicitly approved**, must require
`--mode scenario-research`, an allowlisted `--scenario-id` and version,
explicit source/config/profile identities, a unique protected output
destination, and a separate scenario report schema. CLI defaults remain
strict/evidence mode. The CLI must reject scenario flags in NSE
`EXECUTION_VALID`/PAPER/live contexts. This is interface specification
only; no CLI is implemented under #254.

## 3. Provenance, reproducibility and output isolation

A scenario calculation identity must include, at minimum:

- source provider/venue/instrument/traded-price semantics and immutable
  qualified-or-diagnostic audit status, protected SF-088 source evidence ID,
  dataset content hash, 1m grid/coverage and 5m close digest;
- dataset identity, strategy ID/version + canonical config ID/hash,
  indicator/engine calculation version and UTC measurement/pre-roll bounds;
- exact `ScenarioAssumptionSet` canonical mapping, id/version and *semantic
  hash* including all subrule IDs/versions and allowed numeric parameters;
- historical fill/slippage profile semantic ID and version, historical
  price-mode and unresolved tick-rule marker;
- scenario simulator calculation/version, session policy identity, separate
  conditional scenario-run ID and model-specific opportunity/outcome IDs;
- code/repository revision where available as **actual** provenance, never
  fabricated historical metadata.

#### Canonical execution manifest and identity — M2 contract correction

The preceding list is **mandatory**, not optional metadata. Avoid an
illustrative positional `H(...)` preimage that accidentally omits a
field. Instead define a versioned canonical, typed
`ScenarioExecutionManifest` with the following **complete minimum**
identity-bearing groups (any newly authoritative result-changing input
must be added to the mapping and calculation version before execution):

| Manifest group | Required identity-bearing contents |
|---|---|
| `mode_and_schema` | `SCENARIO_RESEARCH` discriminator, scenario manifest schema version, scenario simulator calculation ID/version; disjoint strict-mode namespace |
| `source` | provider/venue, instrument/contract ID, traded-price basis, immutable source-generation/audit proof ID, qualification status, dataset ID and exact content hash, resolution, full source interval, 1m coverage and 5m aggregation/digest identity |
| `strategy` | strategy ID **and version**, canonical config ID **and hash**, indicator engine calculation ID/version, completed-candle requirements where identity-relevant |
| `assumptions` | scenario ID **and version**, full canonical five-subpolicy `(id, version)` mapping, all numerical options and `scenario_assumption_semantic_hash` |
| `fills` | frozen RAW execution profile ID **and version** and exact semantic mapping/hash (not just friendly name), price mode, historically unresolved tick-applicability marker |
| `session_and_window` | market/session policy ID **and version**, UTC pre-roll start/end and measured IS/OOS boundaries, including their half-open semantics |
| `resource_policy` | explicit versioned budget-policy ID and semantic hash, **all finite computational limits** governing allowed state/event/transition counts and evidence/trace volume, plus exhaustion behavior |
| `implementation` | actual source-code/repository revision and canonicalization/calculation versions used for the run; never inferred or invented provider/historical metadata |

**Planned computation identity:**
`scenario_run_id = H("scenario-run-v1", canonical(ScenarioExecutionManifest))`.
The resource-policy semantic mapping **must be in this preimage**, so a
different budget cap cannot silently share a run ID even if the input
bars and model assumptions are identical. The manifest is validated and
frozen **before** source iteration or outputs; defaults may not be
injected afterwards. Do not use any result-computed digest in the
run-ID preimage (avoid self-reference).

**Produced result identity:**
`scenario_result_id = H("scenario-result-v1", scenario_run_id,
canonical(result_evidence_digest, completion_status,
terminal_boundary, unresolved_reasons, output_schema_version))`.
Every output records its run ID, full input manifest and canonical result
digest; the latter binds the ordered causal/conditional evidence and
measured decision coverage without overwriting a previously protected
artifact. An exhaustion record must retain the **same** run ID, budget
policy ID/version and limits, attempted count, last complete source
bucket, failing source boundary, pre-failure lifecycle/state identifiers,
reason and explicit `SCENARIO_UNSUPPORTED` / termination status. A
budget change mandates a different run identity and output namespace.
No partial/economically selected state may be reported as completed.

Use deterministic canonical Decimal strings, sorted mapping fields,
ordered lifecycle/source references, timezone-aware UTC timestamps and
versioned serialization. The *same manifest and source* must reproduce
identical result bytes and IDs; changing any source, strategy, config,
scenario/subpolicy, fill, session, window, budget or calculation version
must alter the appropriate calculation identity. Cross-version scenario
IDs and strict result IDs occupy distinct namespaces. Future tests must
prove identity separation, budget sensitivity, invalid/unknown fields,
byte-identical replay and failure evidence.

Output must be explicitly `SCENARIO_CONDITIONED` and
`execution_valid=false`; never `PASS_DIAGNOSTIC`,
`FAIL_DIAGNOSTIC` or the frozen SF-096 result schema. Use **new,
non-overwriting** protected local output paths with manifest/digest and
audit chronology. A pre-existing path or conflicting manifest fails; no
overwrite or backfill of source metadata. No raw protected SF-088 data or
full traces in GitHub/Google Drive. Only sanitized and verified reports may
be transferred under existing approved procedures.

A future comparable strict/scenario join uses source + dataset +
strategy/config + *signal interval* + explicit engine/model-version fields.
It must **not** assume identical execution opportunity IDs or cast a modeled
scenario fill into a strict historical fact.

## 4. Hypothetical ambiguity example (synthetic only)

The following **illustrates** consequences of alternative hypothetical
fixed paths: **O-H-L-C is owner-selected for specification finalisation
only**, while O-L-H-C is an unselected comparison, not an approved first
scenario. Neither path is observed chronology; these are not BTC
historical prices.

- One-minute observed candle: `O=101, H=109, L=99, C=102`.
- A previously ARMED synthetic long setup: trigger `103`, invalidation
  and stop `100`, and candidate zero-slippage entry fill `103`.
- Typed strategy post-fill target is `entry + 1.5 × (entry − stop)`
  = `107.5`. No intrabar time cutoff for this illustration.
- **Assume O-H-L-C**: modeled entry at `103`, then modeled target
  `107.5`; result `SCENARIO_CONDITIONED / CLOSED / TARGET / +1.5R`.
- **Assume O-L-H-C**: invalidation `100` happens before trigger;
  result `SCENARIO_CONDITIONED / EXPIRED / no trade R`.
- **Strict ADR-011:** observed H/L alone cannot distinguish those histories;
  neither path is historical truth. The strict result remains
  bounded-ambiguous; never replace it with either scenario output.

The example deliberately excludes gap prices, ties and timed cutoffs.
The specific first-scenario policies are selected for specification
finalisation in #253/#255; this synthetic comparison does not exercise
them, and no policy becomes operative before final normative Gate B.

## 5. Alternatives and recommendation

| Alternative | Strength | Material failure | Position |
|---|---|---|---|
| Retain strict-only fail-closed | Highest historical integrity | Cannot explore conditional performance past OPEN ambiguity | Keep as default and strict baseline |
| Audited exhaustive possible-worlds (#251) | Retains all compatible paths | Large branch/state growth; high correctness/audit cost | Distinct deferred research direction |
| Higher-resolution market trades (SF-098) | Can establish actual order if qualified | Historical coverage/contract proof unknown | Pursue independently |
| **One registered deterministic assumed path** | Small, predictable, reproducible scenario sensitivity | Model-dependent trade sets; path choice material | **Owner-selected for specification finalisation** under #253; not operative or normative until final Gate B |
| A basket of optimistic/adverse/random paths | Potential sensitivity envelope | Easy post-hoc cherry-picking; semantics/multiplicity unclear | Reject as first increment |
| Reuse strict runner with `force_close`/implicit choose | Minimal code | Mixes evidence and fiction; breaks frozen identities | Reject |

Do **not** choose the path that improves OOS or resolves SF-096 the most.
The chosen model must be declared *before* any scenario-performance output
is inspected. The architecture evaluates **support for a fixed-path
assumption vocabulary**, not the validity of any particular scenario.

## 6. Failure and adversarial pressure-test matrix

| Case | Candidate conceptual action | Mandatory disclosure / failure |
|---|---|---|
| `ENTRY_VS_POST_FILL_TARGET` | Hypothetical sequence determines whether entry precedes target; compute target only after modeled fill | If path/tie unknown: `SCENARIO_UNSUPPORTED`; never imply strict CLOSED |
| `ENTRY_VS_INVALIDATION` | Apply declared order; possible conditional entry vs expiry | Strict `OPEN_POSSIBLE` and BOUNDED_FLAT classifications unchanged |
| `ENTRY_VS_POST_FILL_STOP` | Model entry fill and stop reach in order | Stop cannot be evaluated pre-entry as post-fill stop |
| Same-bar STOP/TARGET | First reached in declared ordered path, if no unresolved tie | Neither chosen exit is observed |
| Gap through entry or stop | Use observed open as eligible base, then selected profile slippage | No trigger-price improvement or synthetic gap tick |
| In-minute expiry/session cutoff | Only model if accepted explicit time-order rule exists | Otherwise `SCENARIO_UNSUPPORTED` — no invented tick time |
| UTC midnight | Carry scenario OPEN state continuously | No forced exit solely for calendar date |
| Dataset end OPEN/ARMED | Preserve conditional unresolved lifecycle | No invented terminal price or exit |
| Missing/corrupt candle | Stop with source-quality reason | No candle repair, interpolation or path guessing |
| Non-positive risk / unsupported post-fill economics | Reject per existing strategy/domain contract | No parameter substitution |
| Resource budget exceeded | Terminate with source and prior state/budget provenance | No branch pruning/hidden partial result |
| NSE execution-valid, PAPER/live | Scenario mode inaccessible | Existing identity/result and safety semantics unchanged |

The eventual code implementation must exercise at least three different
strategy shapes **where practicable** under ADR-008; the specification is
strategy-neutral for the **currently accepted long-entry lifecycle family**,
not for shorts, multi-leg, targetless or arbitrary conditional orders.

## 7. Compatibility and proof requirements for a future implementation

- Test unchanged strict `FAIL_CLOSED_V1`, `BOUNDED_FLAT_V1`,
  and legacy NSE result IDs/semantic bytes and session exit semantics.
- Test distinct strict vs scenario run/signal/outcome/result identities
  without collisions, and repeatable scenario result bytes.
- Prove ordered hypothetical paths never alter canonical five-minute candle
  decisions, signal eligibility, strategy configuration, source bars or
  historical effective-tick status.
- Test all rows of the pressure matrix, invalid assumptions, missing input
  provenance, ambiguous event ties, unsupported timestamp ordering and
  unsafe mode/CLI combinations.
- Validate original protected SF-096 result hashes remain untouched and
  that a new scenario report cannot be loaded as a strict result.
- Research outputs must identify model dependency and may only use
  preregistered sensitivity/report interpretation from #255, not ordinary
  unconditional historical win rate or profit.
- No implementation/experiment issue, branch merge, production code or
  real BTC experiment under #254.

## 8. Interface with #255 and parent decision gate

**Proposed shared vocabulary to reconcile with 04:** `OBSERVED_SOURCE`,
`STRICT_INFERABLE`, `STRICT_AMBIGUOUS`,
`SCENARIO_CONDITIONED`, `SCENARIO_UNSUPPORTED`,
`SOURCE_UNQUALIFIED`; strict-vs-scenario ID namespaces; scenario
assumption hash; conditional opportunity/fill/outcome flags; `execution_valid=false`.

**04 owns** the preregistered hypothesis, named scenario rule choices,
ordered-path/tie rules, sensitivity envelope, window/completeness
thresholds, IS/OOS discipline, metrics, conclusions and reporting format.
**02 owns** the typed machinery and audit boundary. Neither can
unilaterally approve strategy-rule changes.

**Parent #253 decision and remaining final Gate B requirements:**

1. **Selection approved for specification finalisation:** the single
   hypothetical O→H→L→C monotone first-crossing path and all five
   explicit versioned subpolicies, including tie rejection, observed
   Open gap base, last-close-before-5m-expiry and once-only profile
   composition; see owner decision #6694636203.
2. **Research interpretation selected for specification finalisation:**
   complete frozen IS/OOS grid, zero measured `SCENARIO_UNSUPPORTED`
   before point metrics and separate methodology sufficiency labels.
3. **Strategy-owner disposition recorded:**
   `STRATEGY_SEMANTICS_UNCHANGED` on #253; no strategy rule change.
4. **Still pending final Gate B:** exact-head cross-contract/DoD review,
   independent review or an explicit approved disposition, and formal
   acceptance of the normative ADR-011 amendment and #255 validation
   contract before merging or creating any later implementation issue.

**Current coordination status:** #255 remains open; its corrected draft
PR #257 at head `1ba45856bc4598d80c4e02bfe1776139bbe13713`
explicitly reconciles all five subpolicy `(id, version)` pairs, proposed
ordering, economics and evidence labels with this architecture. Strategy
owner 01 has recorded `STRATEGY_SEMANTICS_UNCHANGED` for the unchanged
scenario semantics. This is **contract compatibility, not approval**:
#253 has approved the material assumption selection for specification
finalisation only. Final normative Gate B acceptance and required review/
merge evidence remain pending before either proposal becomes operative.
