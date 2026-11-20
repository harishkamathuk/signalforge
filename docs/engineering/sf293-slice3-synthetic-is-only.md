# SF-293 Slice 3 — private synthetic-only IS reporting demonstration

**Scope:** This is an engineering interface description, **not** a new protected economic-study approval, strategy specification, historical cost policy, OOS release decision or Gate D. The normative [SF-293 ER/G requirements](../research/sf293-economic-study-traceability-v1.md), [economic Gate D checklist](prospective-economic-gate-d-checklist.md) and [SF-283 reportability](sf283-persisted-reportability.md) remain authoritative. Owner scope and F1 residual: [#293 decision #7046025170](https://github.com/harishkamathuk/signalforge/issues/293#issuecomment-7046025170).

## Entry point and trust boundary

`scripts/sf293_is_only_report.py --root ABSOLUTE_PRIVATE_DIR --set SAFE_SET_NAME --recipient SAFE_LOCAL_RECIPIENT` is **synthetic TEST_ONLY**. The custodian supplies a pre-existing `0700` root and `0700` set subdirectory containing exactly five `0600` regular, unlinked, non-symlink files:

- `scenario-result.json` (immutable canonical v2);
- `source-quality.json` and `strict-reference.json` (independent canonical companions, rebound to the result);
- `test-cost-assumptions.json` (invented one-unit long TEST_QUOTE assumptions);
- `test-only-grant.json` (explicit **local mock** grant, not a protected owner approval).

The grant contract `sf293-slice3-test-only-local-grant-v1` declares `SYNTHETIC_TEST_ONLY_LOCAL_FIXTURE`, `IS_ONLY`, study ID, matrix revision, grant ID, recipient, approved/unrevoked state, not-before/expiry UTC, implementation revision, RAW profile, scenario-result ID, exact result/source/strict/cost SHA-256, split/start and cost model ID/version. A changed full set requires a separately rebound grant. This synthetic demonstration does **not** establish SF-296 T2 guarded custody, historical B3 authenticity or actual study-release permission. No network grants, cross-profile comparisons or protected input is accepted.

## Scientific/integrity separation

The original three-argument `verify_v2_structure()` remains **FULL** and unchanged in meaning for existing SF-296 clients. The new private call `science_scope="IS"` retains **full-window** original canonical v2/companions, SHA and producer/proof identity, lifecycle and saved modeled-trace integrity checks. Its scientific source and ADR-011 strict completeness checks apply only to **IS**, although the OOS evidence's structural count/interval/proof consistency is still checked. Invalid OOS structure blocks with generic denial; genuinely incomplete OOS scientific coverage does not withhold qualified IS. An incomplete IS science or required IS funding entry is `WITHHELD`.

Only signals ending by split are IS; a 1m event starting at split belongs OOS. IS-originated positions not terminal **before** split are projected as right-censored at the cutoff; no eventual post-split lifecycle leaks. Independent qualified CLOSED IS-contained outcomes alone supply matched gross and after-cost R. Existing Slice 2 fee/Decimal calculations are reused but never run as full-window economic output. Any user-facing source/strict or cost identity is an aggregate/public-safe IS classification, **not** a global result/receipt/hash.

## Disclosure

Success `IS_ONLY_QUALIFIED` prints **one** complete closed allowlist containing only aggregate IS counts/denominators, gross/adjusted modeled R, artificial fee/funding totals, limitations and non-identifying study metadata, with `oos=SEALED`. The output explicitly says `SCENARIO_CONDITIONED`, `SYNTHETIC_TEST_ONLY`, `execution_valid=false`, `LOCAL_SYNTHETIC_T1_NOT_T2`; **not observed BTC profitability**. No trade rows, prices, OOS window, global CLOSED/CROSS_WINDOW, masks, full SHA, grant IDs, subprocess logs, receipts or output files.

Failure outputs are fixed JSON classes `RELEASE_BLOCKED` (invalid authority/custody/full integrity, including corrupt OOS) or `WITHHELD` (genuine IS scientific/cost insufficiency). No partial metrics, path/exception echo or durable report. The owner accepts the one-bit generic release-versus-denial observation for **corrupt** OOS, not OOS economic disclosure; independently valid and rebound identical-IS sets must have byte-identical public responses despite different OOS science, eventual states or OOS funding omission.

**No protected Gate D/E, Slice 4, PAPER/live, OOS release, actual BTC cost source or historical economic study is enabled.** Tests under `tests/unit/research/test_scenario_execution.py` provide the synthetic grant fixture and independent producer/adversarial differential oracles.
