# SF-260 B3 — Independent ADR-011 strict one-minute eligibility evidence

**Status:** prospective implementation only; protected historical execution is **not authorised**.
Authority: [00.01 #6859554840](https://github.com/harishkamathuk/signalforge/issues/253#issuecomment-6859554840);
[04 accepted methodology #6859734414](https://github.com/harishkamathuk/signalforge/issues/260#issuecomment-6859734414).
This is not a revision of frozen Stage 6, historical strict strategy policy or v1 identities.

## Producer boundary

`produce_strict_reference_evidence(request, scenario_result, path)` independently
runs the existing ADR-011 `HistoricalBarExecutionRunner` in
`RAW_DIAGNOSTIC / FAIL_CLOSED_V1` mode, with the same exact approved
source/strategy/config/profile/engine version as the scenario manifest.
A read-only audit callback records the strict engine's **state before each
canonical one-minute bucket** and the independently processed disposition.
The result identity, source manifest/diagnostic identity, strategy, profile,
calculation, UTC windows and repository revision are bound into the canonical
strict companion. A companion is created exclusively and never overwritten.

The audit hook is optional and does not alter fills, signal ordering, outcomes
or existing historical result identities. It is prohibited outside the
RAW_DIAGNOSTIC FAIL_CLOSED_V1 lane.

## Interval classification

Each UTC minute start `t` denotes `[t,t+1m)`. The strict engine makes
`t` **known eligible (E)** only when ARMED or OPEN exists **before**
processing that minute. A strategy decision on a five-minute candle ending
at `t+1m` cannot make that bucket eligible. The terminal bucket remains
eligible. Known inactive processed buckets are **known ineligible (I)**.

A known eligible minute is **assessed** when accepted ADR-011 rules completed
its causal bar evaluation; a bounded competing outcome with a reason and
the current reachability bucket is **ambiguous**, counted once. An unsupported
or unresolved disposition without such traceable bounded alternatives is
**eligible-unassessed**, not an assessed-zero minute.

The default strict runner stops at the first unresolved or OPEN-possible
bounded outcome. All later unprocessed measured buckets are
**eligibility-indeterminate (?)**, not eligible or ineligible. The producer
records the stop certainty/reasons and the known prefix. It never chooses
possible worlds, extends the strict engine or inspects a scenario OHLC path.
A final unresolved ARMED/OPEN opportunity is separately recorded as
`end_terminal_uncertainty` (state and reasons), not mistaken for a
within-minute ambiguity or an early-stop source suffix.

## Additive canonical companion proof

The existing `scenario-strict-reference-v1` fields remain unchanged:
`eligible_intervals` continues to mean **supplied assessed keys**, and
`assessment` retains the original `ASSESSED`/ `NOT_ASSESSED` meaning.
The independent B3 producer adds `strict_coverage_proof` with version
`adr011-strict-eligible-1m-v1`. Per IS and OOS:

- `window_1m_expected`, unique `eligibility_1m_mask` over `E/I/?`;
- `known_eligible`, `known_ineligible`, `eligibility_indeterminate`;
- `expected_eligible` numeric **only when no indeterminate keys**;
- assessed-mask, `assessed`, `unassessed`, `ambiguous`, explicit status and
  incomplete reasons.

Exact laws: `window_1m_expected = E + I + ?`,
`known_eligible = assessed + unassessed`, `ambiguous <= assessed`.
The independent whole-window expected-eligible denominator is
`NOT_ESTABLISHED` (canonical null) if any eligibility is indeterminate.
Zero eligible is proved only by complete independent traversal with every
measured minute known ineligible (`ASSESSED_ZERO_ELIGIBLE`), never by an
empty unexecuted assessment.

The saved-byte reader checks unique canonical membership, counts, exact
per-window masks, UTC ambiguity keys, stop evidence, and manifest identity.
**Both** measured windows must have zero indeterminate and zero eligible-
unassessed intervals, or the mandatory gross-R report is fully WITHHELD.
The source-quality companion also remains mandatory. A valid synthetic
SF-283 legacy fixture may still test its earlier isolated metric contract,
but it does **not** represent a B3 historical readiness result; any protected
or new B3-producer companion lacking independent coverage proof is rejected.

## Operational limits

The producer is not called by the read-only saved-byte reporting CLI.
Missing/corrupt source evidence, unsupported policy or an invalid audit
fails closed rather than creating a complete companion. Generated masks,
reasons and counts are diagnostics, not observed ticks, execution-valid fills
or historical profitability. Source status remains
`UNQUALIFIED_HISTORICAL_METADATA`; Gate E, OOS release and PAPER/live are
not approved.

Synthetic acceptance evidence covers full/no-opportunity traversal, terminal
minute, completed-five-minute split boundary, OPEN-possible early stop,
indeterminate suffix, deliberately rehashed mask/provenance contradictions,
writer determinism and preservation of legacy run identity. No protected
source or economic output is inspected.
