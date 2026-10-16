# SF-083 — Local acquisition CLI (experimental)

The runnable CLI is `tools/research/sf083_acquire_sample.py`. Install SignalForge
(`python -m pip install -e .`) and install the SignalForge nsemine fork by an
**immutable Git commit**. For this corrective PR, the required fork change is in
`harishkamathuk/signalforge-nsemine` PR #8; use its final reviewed commit when
testing this branch.

A Git/VCS install is mandatory because the acquisition command verifies the
installed distribution's PEP 610 `direct_url.json` provenance **before importing
provider code or making resolver/network calls**. The provenance must identify:

- `https://github.com/harishkamathuk/signalforge-nsemine`;
- Git as the VCS;
- the exact 40-character lowercase commit supplied with `--revision`.

A package-version match, module path, editable checkout, filename or callable
signature is not sufficient evidence of the installed acquisition implementation.

Neither nsemine nor broker credentials are imported by offline verification.

## Required prerequisites

Register the exact NSE EQ symbol, one regular historical NSE session, the
exchange-calendar reference and a source/use/retention basis in SF-083 **before**
examining the outcome. Put the source-use evidence in a local text file. A
nonempty evidence file is a workflow guard **not proof of legal authorization**.
Confirm allowed acquisition and local retention independently. Restrict
permissions of the private output directory and do not add it to Git.

For the preregistered first experiment, the requested identity is TCS/EQ and the
session is 2026-10-09. Existing captures must not be overwritten or retroactively
relabelled.

## Commands

After the corrective fork PR has passed its separate review, install its immutable
reviewed commit and pass that same commit to the command:

```bash
python -m pip install "git+https://github.com/harishkamathuk/signalforge-nsemine.git@PINNED_REVIEWED_COMMIT"

mkdir -p /path/outside-repository/sf083-sample
python tools/research/sf083_acquire_sample.py acquire \
  --symbol TCS \
  --session 2026-10-09 \
  --series EQ \
  --revision PINNED_REVIEWED_COMMIT \
  --calendar-reference NSE_REGULAR_SESSION_REFERENCE \
  --entitlement-evidence /path/private/source-use-evidence.txt \
  --output /path/outside-repository/sf083-sample
```

If the installed VCS commit or repository differs from `--revision`, or PEP 610
VCS provenance is absent, acquisition fails before provider import. After import,
the actual `nsemine.historical` module path must match the installed distribution's
module location before any provider resolver or network access. PEP 610 is
installation metadata, not cryptographic proof of package content or entitlement.

## Instrument identity

The acquisition performs two explicitly linked provider operations:

1. `nsemine.historical.search_stock_instruments(stock_symbol="TCS", segment="EQ")`
   returns the provider candidate dictionaries without symbol normalization or
   implicit first-candidate selection. A malformed candidate set is an explicit
   provider-schema failure; malformed entries are not silently discarded.
2. SignalForge accepts exactly one candidate only when the **provider-native**
   fields establish TCS/EQ cash-equity identity, extracts its provider
   `scripcode`, and supplies that exact token to
   `get_stock_historical_data_by_instrument(...)`. That direct-token API performs
   no second symbol resolution.

Accepted evidence is deliberately narrow:

- original provider symbol exactly `TCS-EQ` with type `Equity`; or
- original provider symbol `TCS`, provider series field `EQ`, and type
  `Equity`.

A base-symbol candidate with no provider series evidence remains **BLOCKED**.
The previous generic operator-supplied independent-reference fallback has been
removed because hashing a local reference file proves byte integrity but not
independent source attribution. A future source-specific authoritative
instrument-master parser may be considered separately if concrete evidence
requires it.

## Historical response gate

A historical request is not considered a successful bounded capture merely
because an HTTP/SDK call returned.

The decoded response must be a dictionary containing a **non-empty list** in
`data`, with non-empty dictionary entries and no explicit provider error or
`success=false` indication. An absent response, malformed payload, empty
`data`, non-list `data`, malformed rows or error-marked response is BLOCKED
and no success evidence artifacts are written. This is only a structural
capture gate, not canonical OHLCV validation.

This check does not interpret timestamps, candle completion, OHLCV quality or
session semantics. Those remain later evidence gates.

## Evidence artifacts

Only after revision verification, exact provider identity verification and a
non-empty historical response does a successful bounded acquisition publish:

- `resolver-evidence.json` — exact search parameters, every returned provider
  candidate, original selected candidate, selection basis and provider token;
- `sdk-decoded-response.json` — deterministically re-encoded SDK-decoded
  historical JSON, **not original HTTP response bytes**;
- `acquisition-manifest.json` — resolver/response hashes, verified installed
  repository and commit, selected identity and exact historical-request token
  linkage.

The directory must be pre-existing and empty. Writes use exclusive creation and
cleanup on handled publication failures. This is **cleanup-protected, not
crash-atomic**: an abrupt process/power failure can leave partial files, which
must be quarantined rather than reused.

No NSE request is made in CI; tests use fixtures and mocks only.

## Canonicalization stop

Instrument identity and installed-revision evidence are separable from the
remaining source qualification. This command still does **not** automatically
create a canonical `HistoricalBarDataset`.

The captured response is preserved for independent validation. SF-081 timestamp
interpretation remains evidence-qualified, missing conventional minutes must not
be synthesized, and post-15:15 observations must not be treated as ordinary
continuous-session candles without a separately accepted session contract.

Only after the captured response passes the remaining source/canonical quality
checks should the accepted one-session dataset be stored through SF-084.

## Offline verification

Once a validated canonical dataset has been stored with SF-084, run the separate
verification command by its ID in an **OS-level network-isolated** environment:

```bash
python tools/research/sf083_acquire_sample.py offline-verify \
  --dataset-id YOUR_CANONICAL_DATASET_SHA256 \
  --output /path/outside-repository/canonical-store
```

This command imports no nsemine/broker modules; it checks the on-disk sidecar,
canonical content hash, dataset ID and 5m aggregation. An ordinary invocation
alone does not prove OS-level network isolation.

Do not commit real resolver responses, SDK-decoded historical JSON, persisted
canonical bars/sidecars, provider credentials, cookies, tokens or restricted
logs.

## Completion distinction

This corrective implementation addresses the post-merge PR #215 adversarial
findings concerning installed-fork provenance, unsafe generic reference
acceptance, malformed resolver candidates and empty historical responses.

It does **not** itself complete SF-083, approve SF-079 Gate A, prove source-use
rights, prove the full historical timestamp/session contract, or make a captured
response canonical. A fresh real acquisition remains blocked until both
corrective PRs have passed CI and the project's separate final review gate.
