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
