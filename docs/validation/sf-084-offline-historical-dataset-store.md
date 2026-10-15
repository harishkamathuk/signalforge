# SF-084 — Offline historical dataset store

`LocalHistoricalDatasetStore(root)` saves and loads the existing canonical
`HistoricalBarDataset` by `dataset_id`, independently of nsemine and network
connectivity. It uses the established strict JSON historical-fixture format, plus
a SHA-256 digest of the complete serialized file. No new storage service is needed.

```python
from pathlib import Path
from signalforge.research.historical_dataset_store import LocalHistoricalDatasetStore

store = LocalHistoricalDatasetStore(Path("./data/historical"))
dataset_id = store.save(canonical_dataset)
offline_dataset = store.load(dataset_id)
assert offline_dataset.dataset_id == dataset_id
```

The paired `<dataset_id>.json` and `<dataset_id>.sha256` files must remain
together. Both the byte checksum and the reconstructed canonical semantic
identity are checked when loading. Existing identities are not overwritten.
Missing or inconsistent stored files fail explicitly, without fetching or
repairing market data.

`acquired_at`, rejected-row counts and certain operational provenance fields
are **not included** in the pre-existing canonical semantic hash. Their bytes
are retained and checked by the sidecar file digest; a second save with the
same semantic ID but different manifest metadata fails rather than rewriting
the stored version. The sidecar is a local integrity check, not an
independently anchored authenticity or tamper-proof guarantee.

SF-083 should supply one permissible real NSE data session to this store and
verify network-disconnected reload. This task neither acquires data nor
changes Gate A, strategy semantics, or provider qualifications. Do not commit
restricted provider OHLCV files to Git.

## Interrupted writes and recovery

A dataset consists of two files. If a process terminates or storage fails after the
JSON file is created but before the SHA-256 sidecar is published, subsequent
loads and saves deliberately fail closed. There is **no automatic repair**.
Inspect the files and audit the acquisition/source evidence before manually
quarantining the incomplete pair to a separate directory; retry an authorized
save only after that investigation. Never overwrite the original evidence.

Both files are individually flushed and synchronized, followed by a parent
folder synchronization where `O_DIRECTORY` is supported. This improves local
filesystem crash durability but does not promise transactional publication,
recovery from arbitrary hardware faults, or protection against intentional
modification of both the data and sidecar. The loader parses precisely the
bytes whose checksum it verified, without a second file read.

## Canonical duplicate-source evidence

The canonical `HistoricalBarDataset` removes identical upstream duplicate
observations during initial validation while retaining their number in its
manifest. The store serializes only unique canonical bars and uses a specific,
strict canonical-storage reconstruction path that validates the unique bars and
original raw/canonical/duplicate/rejected counts. It does **not** synthesize
duplicate OHLCV records on disk. Save preflights that exact storage decoder
before publishing files; a valid source dataset with duplicates must round-trip
without changing its dataset ID or manifest evidence.
