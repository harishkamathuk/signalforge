# SF-083 — Local acquisition CLI (experimental)

The runnable CLI is `tools/research/sf083_acquire_sample.py`. Install SignalForge
(`python -m pip install -e .`) and install the SignalForge nsemine fork revision
that exposes evidence-safe instrument resolution and direct-token historical
retrieval:

```bash
python -m pip install "git+https://github.com/harishkamathuk/signalforge-nsemine.git@862a8b47921ced89346fdffcf71a38afdb70b35c"
```

Neither nsemine nor broker credentials are imported by offline verification.

## Required prerequisites

Register the exact NSE EQ symbol, one regular historical NSE session, the
exchange-calendar reference and a source/use/retention basis in SF-083 **before**
examining the outcome. Put the source-use evidence in a local text file and
record the actual installed fork commit as `--revision`. A nonempty local
evidence file is a workflow guard **not proof of legal authorization**. Confirm
allowed acquisition and local retention independently. Restrict permissions of
the private output directory and do not add it to Git.

For the preregistered first experiment, the requested identity is TCS/EQ and the
session is 2026-10-09. Existing captures must not be overwritten or retroactively
amended.

## Commands

```bash
mkdir -p /path/outside-repository/sf083-sample
python tools/research/sf083_acquire_sample.py acquire \
  --symbol TCS \
  --session 2026-10-09 \
  --series EQ \
  --revision 862a8b47921ced89346fdffcf71a38afdb70b35c \
  --calendar-reference NSE_REGULAR_SESSION_REFERENCE \
  --entitlement-evidence /path/private/source-use-evidence.txt \
  --output /path/outside-repository/sf083-sample
```

The acquisition now performs two explicitly linked provider operations:

1. `nsemine.historical.search_stock_instruments(stock_symbol="TCS", segment="EQ")`
   returns the provider's original candidate dictionaries without destructive
   symbol normalization or implicit first-candidate selection.
2. SignalForge accepts exactly one candidate only when the original provider
   evidence establishes TCS/EQ cash equity identity, extracts its provider
   `scripcode`, and supplies that exact token to
   `get_stock_historical_data_by_instrument(...)`. The direct-token API performs
   no second symbol resolution.

A provider candidate such as `TCS-EQ` with type `Equity` can establish
series identity directly. A base-symbol-only candidate such as `TCS` is
accepted only if the provider response itself carries an explicit matching
`series=EQ` field. Generic operator-supplied reference metadata is **not** an
automatic identity override. If provider-native evidence does not establish the
requested cash-equity series, acquisition stops before historical price
retrieval and must be recorded as BLOCKED.

Before importing nsemine or making any provider call, the CLI also verifies the
installed Python distribution's PEP 610 `direct_url.json` VCS provenance. The
recorded repository must be the SignalForge nsemine fork and its exact Git
`commit_id` must equal `--revision`. Missing, non-Git, wrong-repository or
wrong-commit provenance fails closed before provider access.

## Evidence artifacts

A successful bounded acquisition publishes three files together into a
pre-existing empty private directory:

- `resolver-evidence.json` — exact search parameters, every returned provider
  candidate, the original selected candidate, selection basis, provider token,
  verification outcome and optional independent-reference provenance;
- `sdk-decoded-response.json` — deterministically re-encoded SDK-decoded
  historical JSON, **not original HTTP response bytes**;
- `acquisition-manifest.json` — SHA-256 identities for resolver and response
  evidence, selected provider identity, exact historical-request token linkage,
  installed package metadata, declared fork revision and limitations.

If identity evidence is ambiguous, contradictory, unsupported, missing a usable
token, the installed VCS provenance cannot be proven, or the direct-token nsemine
API is unavailable, the command fails **before historical price acquisition**.
A historical response must also contain a non-empty `data` list; empty or
malformed payloads are reported as BLOCKED and no success artifacts are
published. If evidence publication fails, the command removes its own partial
artifacts rather than leaving a misleading successful capture.

The installed fork repository/commit is verified from Python distribution VCS
provenance metadata before provider access. Calendar and entitlement evidence
remain operator-supplied workflow inputs and do not by themselves prove
authorization or canonical timestamp semantics. No NSE request is made in CI;
tests use fixtures and mocks only.

## Canonicalization stop

Instrument identity evidence is now separable from the remaining source
qualification. This command still does **not** automatically create a canonical
`HistoricalBarDataset`.

The current historical response is preserved for independent validation. SF-081
timestamp interpretation remains evidence-qualified, missing conventional
minutes must not be synthesized, and post-15:15 observations must not be treated
as ordinary continuous-session candles without a separately accepted session
contract.

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
logs. Sanitized hashes, observed quality counts, mapping limitations and session
references may be recorded on SF-083 when permitted.

## Completion distinction

The instrument-identity and exact-token acquisition boundary can now be exercised
locally with the pinned fork revision. This does **not** by itself complete
SF-083, approve SF-079 Gate A, prove source-use rights, prove the full historical
timestamp/session contract, or make the captured response canonical.

Offline verification still validates a canonical SF-084 dataset by ID; linkage
from a real acquisition into that canonical dataset remains an evidence-dependent
subsequent step.
