# SF-081 — Canonical clock compatibility: evidence boundary

Related: SF-081 #203, fork PR #3 and PR #4, ADR-010 / DATA-004.

This is a **synthetic offline contract proof**, not an acquisition adapter or a replay of real NSE bytes. The bounded RELIANCE observation covered 12 October 2026 09:15–10:15 IST (60 one-minute and 12 five-minute bars), acquired 14 October. Fork merge SHAs: request 8157b8d51ee1f870124c31d1dd125658a89eb421; response 3c642ed08b895e72319e02adc12cd78991c34800. Original hash-addressed evidence belongs to SF-081, and this PR does not recreate or assert new provider evidence.

The test-only timestamp translation mirrors observed wall-clock-shaped milliseconds (final-minute seconds 53–59). A raw value shaped as 09:15:53 UTC represents 09:15:53 Asia/Kolkata wall time, interpreted as 03:45:53 UTC. Canonical interval opening is 03:45:00 UTC. Raw provider encoding, interpreted source instant and canonical bucket remain separately represented.

The tests verify 60 synthetic HistoricalBar instances under the existing full 375-minute session manifest, 315 missing minutes, 12 VALID and 63 MISSING derived five-minute buckets, malformed encoding rejection and a subprocess host-timezone matrix (UTC, Europe/London, Asia/Kolkata). These tests do not invoke code from the external fork and do not prove a production source-to-dataset ingestion.

This does not establish provider-wide wire semantics, candle completion, reliability, retention, legal source use, corporate action adjustments or acquisition approval. No SF-079 Phase B adapter or strategy/simulator changes. **SF-079 Gate A remains BLOCKED.**