"""SF-079 provisional offline mapper: synthetic/provider-shaped fixtures only; no I/O."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json

from signalforge.domain.ids import InstrumentId
from signalforge.domain.market import CandleQuality
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy, HistoricalBar, HistoricalBarDataset,
    HistoricalDatasetManifest,
)

VERSION = "sf079-provisional-synthetic-v1"


def _raw_clock(raw: int) -> datetime:
    if type(raw) is not int or raw % 1000:
        raise ValueError("invalid millisecond precision")
    try:
        wall = datetime.fromtimestamp(raw // 1000, UTC).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("invalid provider-shaped clock") from exc
    if not (time(9, 15) <= wall.time() < time(15, 30)):
        raise ValueError("outside regular session")
    return wall


def map_synthetic_session(
    records: list[dict[str, object]], *,
    session_date: date, instrument: str, provider_symbol: str,
    acquired_at: datetime, fork_revision: str, fixture_sha256: str,
) -> HistoricalBarDataset:
    """Convert declared synthetic 1m rows; fail on corrupt or contradictory input."""
    if not records:
        raise ValueError("empty synthetic fixture")
    if acquired_at.tzinfo is None or acquired_at.utcoffset() is None:
        raise ValueError("acquired_at must be aware")
    if len(fixture_sha256) != 64 or any(c not in "0123456789abcdef" for c in fixture_sha256):
        raise ValueError("invalid fixture digest")
    if len(fork_revision) != 40 or any(c not in "0123456789abcdef" for c in fork_revision):
        raise ValueError("fork revision must be immutable SHA")
    identity = InstrumentId(instrument)
    begin = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    finish = datetime.combine(session_date, time(15, 30), tzinfo=IST)
    bars: list[HistoricalBar] = []
    previous = None
    for item in records:
        if set(item) != {"instrument", "provider_symbol", "time", "open", "high", "low", "close", "volume"}:
            raise ValueError("unexpected synthetic record fields")
        if item["instrument"] != instrument or item["provider_symbol"] != provider_symbol:
            raise ValueError("instrument identity mismatch")
        wall = _raw_clock(item["time"])
        if wall.date() != session_date:
            raise ValueError("unexpected session date")
        opened = wall.replace(second=0, microsecond=0, tzinfo=IST)
        if previous is not None and opened <= previous:
            raise ValueError("duplicate or unordered opening bucket")
        previous = opened
        if not (begin <= opened and opened + timedelta(minutes=1) <= finish):
            raise ValueError("invalid session bucket")
        raw_prices = []
        for field in ("open", "high", "low", "close"):
            value = item[field]
            if not isinstance(value, str) or not value or len(value) > 32:
                raise ValueError("prices must be decimal strings")
            raw_prices.append(Price(Decimal(value)))
        volume = item["volume"]
        if type(volume) is not int:
            raise ValueError("volume must be integer")
        interpreted = wall.replace(tzinfo=IST).astimezone(UTC)
        bars.append(HistoricalBar(
            instrument_id=identity,
            interval=CandleInterval(start=to_utc(opened), end=to_utc(opened + timedelta(minutes=1))),
            open=raw_prices[0], high=raw_prices[1], low=raw_prices[2], close=raw_prices[3],
            volume=volume, quality=CandleQuality.VALID,
            source_provider="synthetic-nsemine-shaped",
            source_record_count=1,
            provider_timestamp_raw=str(item["time"]),
            provider_timestamp_interpreted=interpreted,
            canonicalisation_version=VERSION,
        ))
    manifest = HistoricalDatasetManifest(
        provider="synthetic-nsemine-shaped",
        acquisition_adapter="offline-experimental-only",
        acquisition_version=VERSION + ";fork:" + fork_revision + ";fixture:" + fixture_sha256,
        requested_instrument=instrument, resolved_provider_instrument=provider_symbol,
        instrument_id=identity, requested_start=begin, requested_end=finish,
        returned_start=bars[0].interval.start, returned_end=bars[-1].interval.end,
        interval_minutes=1, acquired_at=acquired_at,
        provider_timestamp_representation="NSE-local wall-clock-shaped epoch milliseconds (synthetic)",
        timezone_interpretation="decode UTC-shaped wall fields as Asia/Kolkata, never UTC instant",
        canonicalisation_version=VERSION,
        expected_session_dates=(session_date,),
        raw_row_count=len(records), canonical_row_count=len(bars),
        missing_interval_count=375-len(bars), duplicate_observation_count=0,
        corrupt_rejected_count=0,
        corporate_action_policy=CorporateActionPolicy.UNKNOWN,
        limitations=("SYNTHETIC / NON-MARKET EVIDENCE; no NSE acquisition",
                     "Not evidence of Gate A qualification or real market strategy performance"),
    )
    return HistoricalBarDataset(manifest=manifest, bars=tuple(bars))


def fixture_digest(records: list[dict[str, object]]) -> str:
    """Content identity of a declared synthetic fixture, not a source response."""
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()
