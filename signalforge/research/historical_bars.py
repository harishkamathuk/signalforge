"""Provider-neutral canonical historical-bar research boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from signalforge.config.identity import config_hash
from signalforge.config.strategy_registry import (
    DEFAULT_STRATEGY_REGISTRY,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.ids import DatasetId, InstrumentId
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval, require_aware, to_ist, to_utc
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.strategy import CompletedCandleStrategyContext, StrategyDecision

_ONE_MINUTE = timedelta(minutes=1)
_FIVE_MINUTES = timedelta(minutes=5)
_SESSION_OPEN = time(9, 15)
_SESSION_END = time(15, 30)
_EXPECTED_FIVE_MINUTE_BARS = 75


class CorporateActionPolicy(StrEnum):
    """Declared price/volume adjustment policy for one historical dataset."""

    RAW_UNADJUSTED = "raw_unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"
    DIVIDEND_ADJUSTED = "dividend_adjusted"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    """Canonical provider-neutral one-minute historical OHLCV observation."""

    instrument_id: InstrumentId
    interval: CandleInterval
    open: Price
    high: Price
    low: Price
    close: Price
    volume: int
    quality: CandleQuality
    source_provider: str
    source_record_count: int
    provider_timestamp_raw: str | None
    provider_timestamp_interpreted: datetime | None
    canonicalisation_version: str

    def __post_init__(self) -> None:
        if self.interval.end - self.interval.start != _ONE_MINUTE:
            raise ValueError("HistoricalBar interval must be exactly one minute")
        start_ist = to_ist(self.interval.start)
        end_ist = to_ist(self.interval.end)
        if start_ist.second or start_ist.microsecond:
            raise ValueError("HistoricalBar start must align to an exact minute")
        if end_ist.second or end_ist.microsecond:
            raise ValueError("HistoricalBar end must align to an exact minute")
        local_start = start_ist.time().replace(tzinfo=None)
        local_end = end_ist.time().replace(tzinfo=None)
        if not (_SESSION_OPEN <= local_start < _SESSION_END):
            raise ValueError("HistoricalBar must start within the regular NSE session")
        if not (time(9, 16) <= local_end <= _SESSION_END):
            raise ValueError("HistoricalBar must end within the regular NSE session")
        if self.quality is not CandleQuality.VALID:
            raise ValueError("Canonical source HistoricalBar quality must be VALID")
        if not self.source_provider.strip():
            raise ValueError("HistoricalBar source_provider must not be empty")
        if not self.canonicalisation_version.strip():
            raise ValueError("HistoricalBar canonicalisation_version must not be empty")
        if isinstance(self.source_record_count, bool) or not isinstance(
            self.source_record_count, int
        ):
            raise TypeError("HistoricalBar source_record_count must be an integer")
        if self.source_record_count <= 0:
            raise ValueError("HistoricalBar source_record_count must be positive")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("HistoricalBar volume must be an integer")
        if self.volume < 0:
            raise ValueError("HistoricalBar volume must not be negative")
        if any(
            price.value <= 0 for price in (self.open, self.high, self.low, self.close)
        ):
            raise ValueError("HistoricalBar prices must be strictly positive")
        if self.high.value < max(
            self.open.value, self.close.value, self.low.value
        ):
            raise ValueError("HistoricalBar high must be at least open, close, and low")
        if self.low.value > min(
            self.open.value, self.close.value, self.high.value
        ):
            raise ValueError("HistoricalBar low must be at most open, close, and high")
        if self.provider_timestamp_interpreted is not None:
            require_aware(self.provider_timestamp_interpreted)
            object.__setattr__(
                self,
                "provider_timestamp_interpreted",
                to_utc(self.provider_timestamp_interpreted),
            )
        object.__setattr__(
            self,
            "interval",
            CandleInterval(
                start=to_utc(self.interval.start),
                end=to_utc(self.interval.end),
            ),
        )

    def semantic_mapping(self) -> dict[str, object]:
        """Return content that materially defines this canonical observation."""

        return {
            "instrument_id": str(self.instrument_id),
            "interval_start": self.interval.start.isoformat(),
            "interval_end": self.interval.end.isoformat(),
            "open": self.open.value,
            "high": self.high.value,
            "low": self.low.value,
            "close": self.close.value,
            "volume": self.volume,
            "quality": self.quality.value,
            "source_provider": self.source_provider,
            "source_record_count": self.source_record_count,
            "provider_timestamp_raw": self.provider_timestamp_raw,
            "provider_timestamp_interpreted": (
                None
                if self.provider_timestamp_interpreted is None
                else self.provider_timestamp_interpreted.isoformat()
            ),
            "canonicalisation_version": self.canonicalisation_version,
        }


@dataclass(frozen=True, slots=True)
class HistoricalDatasetManifest:
    """Typed provenance for one immutable canonical historical-bar dataset."""

    provider: str
    acquisition_adapter: str
    acquisition_version: str
    requested_instrument: str
    resolved_provider_instrument: str
    instrument_id: InstrumentId
    requested_start: datetime
    requested_end: datetime
    returned_start: datetime
    returned_end: datetime
    interval_minutes: int
    acquired_at: datetime
    provider_timestamp_representation: str
    timezone_interpretation: str
    canonicalisation_version: str
    raw_row_count: int
    canonical_row_count: int
    missing_interval_count: int
    duplicate_observation_count: int
    corrupt_rejected_count: int
    corporate_action_policy: CorporateActionPolicy
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "acquisition_adapter",
            "acquisition_version",
            "requested_instrument",
            "resolved_provider_instrument",
            "provider_timestamp_representation",
            "timezone_interpretation",
            "canonicalisation_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"Historical dataset manifest {name} must not be empty")
        timestamp_fields = (
            "requested_start",
            "requested_end",
            "returned_start",
            "returned_end",
            "acquired_at",
        )
        for name in timestamp_fields:
            require_aware(getattr(self, name))
        if self.requested_end <= self.requested_start:
            raise ValueError("Historical dataset requested range must be increasing")
        if self.returned_end <= self.returned_start:
            raise ValueError("Historical dataset returned range must be increasing")
        if (
            self.returned_start < self.requested_start
            or self.returned_end > self.requested_end
        ):
            raise ValueError("Historical dataset returned range must be within requested range")
        if self.interval_minutes != 1:
            raise ValueError("DATA-004 historical source interval must be one minute")
        for name in (
            "raw_row_count",
            "canonical_row_count",
            "missing_interval_count",
            "duplicate_observation_count",
            "corrupt_rejected_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Historical dataset manifest {name} must be an integer")
            if value < 0:
                raise ValueError(f"Historical dataset manifest {name} must not be negative")

        for name in timestamp_fields:
            object.__setattr__(self, name, to_utc(getattr(self, name)))

    def semantic_mapping(self) -> dict[str, object]:
        """Return interpretation provenance excluding operational acquisition time."""

        return {
            "provider": self.provider,
            "acquisition_adapter": self.acquisition_adapter,
            "acquisition_version": self.acquisition_version,
            "requested_instrument": self.requested_instrument,
            "resolved_provider_instrument": self.resolved_provider_instrument,
            "instrument_id": str(self.instrument_id),
            "requested_start": self.requested_start.isoformat(),
            "requested_end": self.requested_end.isoformat(),
            "returned_start": self.returned_start.isoformat(),
            "returned_end": self.returned_end.isoformat(),
            "interval_minutes": self.interval_minutes,
            "provider_timestamp_representation": self.provider_timestamp_representation,
            "timezone_interpretation": self.timezone_interpretation,
            "canonicalisation_version": self.canonicalisation_version,
            "raw_row_count": self.raw_row_count,
            "canonical_row_count": self.canonical_row_count,
            "missing_interval_count": self.missing_interval_count,
            "duplicate_observation_count": self.duplicate_observation_count,
            "corrupt_rejected_count": self.corrupt_rejected_count,
            "corporate_action_policy": self.corporate_action_policy.value,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class HistoricalBarDataset:
    """Validated canonical one-instrument historical one-minute dataset."""

    manifest: HistoricalDatasetManifest
    bars: tuple[HistoricalBar, ...]

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("HistoricalBarDataset requires at least one bar")
        canonical: list[HistoricalBar] = []
        previous_start: datetime | None = None
        by_start: dict[datetime, HistoricalBar] = {}
        duplicate_count = 0

        for bar in self.bars:
            if bar.instrument_id != self.manifest.instrument_id:
                raise ValueError("Historical bar instrument contradicts dataset manifest")
            if bar.source_provider != self.manifest.provider:
                raise ValueError("Historical bar provider contradicts dataset manifest")
            if bar.canonicalisation_version != self.manifest.canonicalisation_version:
                raise ValueError("Historical bar canonicalisation version contradicts manifest")
            start = bar.interval.start
            existing = by_start.get(start)
            if existing is not None:
                if existing != bar:
                    raise ValueError("Contradictory duplicate historical bar bucket")
                duplicate_count += 1
                continue
            if previous_start is not None and start <= previous_start:
                raise ValueError("Historical bars must use strict canonical chronological order")
            by_start[start] = bar
            canonical.append(bar)
            previous_start = start

        if duplicate_count != self.manifest.duplicate_observation_count:
            raise ValueError("Historical duplicate count contradicts dataset manifest")
        if len(canonical) != self.manifest.canonical_row_count:
            raise ValueError("Historical canonical row count contradicts dataset manifest")
        first = canonical[0].interval.start
        last = canonical[-1].interval.end
        if first != self.manifest.returned_start or last != self.manifest.returned_end:
            raise ValueError("Historical returned range contradicts canonical bar content")
        object.__setattr__(self, "bars", tuple(canonical))

    @property
    def content_hash(self) -> str:
        """Return semantic content identity independent of path/acquisition wall clock."""

        return config_hash(
            {
                "manifest": self.manifest.semantic_mapping(),
                "bars": [bar.semantic_mapping() for bar in self.bars],
            }
        )

    @property
    def dataset_id(self) -> DatasetId:
        """Return the canonical historical dataset identifier."""

        return DatasetId(self.content_hash)

    @property
    def session_dates(self) -> tuple[date, ...]:
        """Return covered NSE local session dates in deterministic order."""

        return tuple(sorted({to_ist(bar.interval.start).date() for bar in self.bars}))


@dataclass(frozen=True, slots=True)
class HistoricalDecisionEvidence:
    """Deterministic projection of one Strategy decision from historical bars."""

    interval_start: datetime
    interval_end: datetime
    completed_regular_session_candles: int
    indicator_ready: bool
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalBarResearchResult:
    """Deterministic signal-evaluation result without execution/lifecycle simulation."""

    dataset_id: DatasetId
    strategy_id: str
    strategy_version: str
    config_hash: str
    engine_calculation_version: str
    derived_candles: int
    valid_candles: int
    incomplete_candles: int
    missing_candles: int
    skipped_after_continuity_break: int
    decisions: tuple[HistoricalDecisionEvidence, ...]

    def semantic_mapping(self) -> dict[str, object]:
        """Return stable machine-readable research evidence."""

        return {
            "dataset_id": str(self.dataset_id),
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "config_hash": self.config_hash,
            "engine_calculation_version": self.engine_calculation_version,
            "derived_candles": self.derived_candles,
            "valid_candles": self.valid_candles,
            "incomplete_candles": self.incomplete_candles,
            "missing_candles": self.missing_candles,
            "skipped_after_continuity_break": self.skipped_after_continuity_break,
            "decisions": [
                {
                    "interval_start": item.interval_start.isoformat(),
                    "interval_end": item.interval_end.isoformat(),
                    "completed_regular_session_candles": item.completed_regular_session_candles,
                    "indicator_ready": item.indicator_ready,
                    "qualified": item.qualified,
                    "actionable": item.actionable,
                    "reasons": list(item.reasons),
                }
                for item in self.decisions
            ],
        }


def aggregate_one_minute_to_five_minute(
    dataset: HistoricalBarDataset,
) -> tuple[CompletedCandle, ...]:
    """Derive the complete canonical NSE five-minute grid for covered sessions."""

    by_start = {bar.interval.start: bar for bar in dataset.bars}
    output: list[CompletedCandle] = []

    for session_date in dataset.session_dates:
        session_start = datetime.combine(session_date, _SESSION_OPEN, tzinfo=IST)
        for index in range(_EXPECTED_FIVE_MINUTE_BARS):
            bucket_start_ist = session_start + index * _FIVE_MINUTES
            bucket_start = to_utc(bucket_start_ist)
            expected_starts = tuple(
                bucket_start + minute * _ONE_MINUTE for minute in range(5)
            )
            constituents = tuple(
                by_start[start] for start in expected_starts if start in by_start
            )
            interval = CandleInterval(
                start=bucket_start,
                end=bucket_start + _FIVE_MINUTES,
            )
            if not constituents:
                output.append(
                    CompletedCandle(
                        instrument_id=dataset.manifest.instrument_id,
                        interval=interval,
                        quality=CandleQuality.MISSING,
                        open=None,
                        high=None,
                        low=None,
                        close=None,
                        volume=None,
                        source="historical-1m-derived",
                        source_event_count=0,
                    )
                )
                continue

            quality = (
                CandleQuality.VALID
                if len(constituents) == 5
                else CandleQuality.INCOMPLETE
            )
            output.append(
                CompletedCandle(
                    instrument_id=dataset.manifest.instrument_id,
                    interval=interval,
                    quality=quality,
                    open=constituents[0].open,
                    high=Price(max(item.high.value for item in constituents)),
                    low=Price(min(item.low.value for item in constituents)),
                    close=constituents[-1].close,
                    volume=sum(item.volume for item in constituents),
                    source="historical-1m-derived",
                    source_event_count=sum(item.source_record_count for item in constituents),
                )
            )

    return tuple(output)


class HistoricalBarResearchRunner:
    """Run completed-candle strategy evaluation over canonical historical bars."""

    def __init__(
        self,
        *,
        registry: StrategyRegistry = DEFAULT_STRATEGY_REGISTRY,
    ) -> None:
        self._registry = registry

    def run(
        self,
        dataset: HistoricalBarDataset,
        *,
        strategy_selection: StrategySelection,
        engine_calculation_version: str,
    ) -> HistoricalBarResearchResult:
        """Evaluate canonical completed bars without simulating trades or MarketEvents."""

        if not engine_calculation_version.strip():
            raise ValueError("engine_calculation_version must not be empty")
        strategy = self._registry.resolve(strategy_selection)
        engine = IndicatorEngine(
            dataset.manifest.instrument_id,
            engine_calculation_version,
            requirements=strategy.indicator_requirements,
        )
        decisions: list[HistoricalDecisionEvidence] = []
        valid = 0
        incomplete = 0
        missing = 0
        skipped_after_break = 0
        completed_count = 0
        continuity_broken = False

        derived = aggregate_one_minute_to_five_minute(dataset)
        for candle in derived:
            if candle.quality is CandleQuality.INCOMPLETE:
                incomplete += 1
                continuity_broken = True
                engine.break_continuity()
                continue
            if candle.quality is CandleQuality.MISSING:
                missing += 1
                continuity_broken = True
                engine.break_continuity()
                continue
            if candle.quality is not CandleQuality.VALID:
                raise ValueError("Unexpected historical derived candle quality")
            valid += 1
            if continuity_broken:
                skipped_after_break += 1
                continue

            snapshot = engine.update(candle)
            completed_count += 1
            decision: StrategyDecision = strategy.evaluate_completed_candle(
                CompletedCandleStrategyContext(
                    candle=candle,
                    indicators=snapshot,
                    completed_regular_session_candles=completed_count,
                    continuity=IndicatorContinuity.HEALTHY,
                    feed_state=None,
                )
            )
            decisions.append(
                HistoricalDecisionEvidence(
                    interval_start=to_utc(candle.interval.start),
                    interval_end=to_utc(candle.interval.end),
                    completed_regular_session_candles=completed_count,
                    indicator_ready=snapshot.ready,
                    qualified=decision.qualified,
                    actionable=decision.actionable,
                    reasons=decision.reasons,
                )
            )

        return HistoricalBarResearchResult(
            dataset_id=dataset.dataset_id,
            strategy_id=strategy.identity.strategy_id,
            strategy_version=strategy.identity.strategy_version,
            config_hash=strategy.config_identity.config_hash,
            engine_calculation_version=engine_calculation_version,
            derived_candles=len(derived),
            valid_candles=valid,
            incomplete_candles=incomplete,
            missing_candles=missing,
            skipped_after_continuity_break=skipped_after_break,
            decisions=tuple(decisions),
        )


def load_historical_bar_fixture(path: Path) -> HistoricalBarDataset:
    """Load one strict repository-local JSON historical-bar fixture."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Historical fixture root must be an object")
    manifest_raw = _mapping(payload.get("manifest"), "manifest")
    bars_raw = payload.get("bars")
    if not isinstance(bars_raw, list):
        raise ValueError("Historical fixture bars must be a list")

    instrument_id = InstrumentId(_string(manifest_raw, "instrument_id"))
    manifest = HistoricalDatasetManifest(
        provider=_string(manifest_raw, "provider"),
        acquisition_adapter=_string(manifest_raw, "acquisition_adapter"),
        acquisition_version=_string(manifest_raw, "acquisition_version"),
        requested_instrument=_string(manifest_raw, "requested_instrument"),
        resolved_provider_instrument=_string(manifest_raw, "resolved_provider_instrument"),
        instrument_id=instrument_id,
        requested_start=_datetime(manifest_raw, "requested_start"),
        requested_end=_datetime(manifest_raw, "requested_end"),
        returned_start=_datetime(manifest_raw, "returned_start"),
        returned_end=_datetime(manifest_raw, "returned_end"),
        interval_minutes=_integer(manifest_raw, "interval_minutes"),
        acquired_at=_datetime(manifest_raw, "acquired_at"),
        provider_timestamp_representation=_string(
            manifest_raw, "provider_timestamp_representation"
        ),
        timezone_interpretation=_string(manifest_raw, "timezone_interpretation"),
        canonicalisation_version=_string(manifest_raw, "canonicalisation_version"),
        raw_row_count=_integer(manifest_raw, "raw_row_count"),
        canonical_row_count=_integer(manifest_raw, "canonical_row_count"),
        missing_interval_count=_integer(manifest_raw, "missing_interval_count"),
        duplicate_observation_count=_integer(
            manifest_raw, "duplicate_observation_count"
        ),
        corrupt_rejected_count=_integer(manifest_raw, "corrupt_rejected_count"),
        corporate_action_policy=CorporateActionPolicy(
            _string(manifest_raw, "corporate_action_policy")
        ),
        limitations=tuple(_string_list(manifest_raw.get("limitations"), "limitations")),
    )

    bars: list[HistoricalBar] = []
    for index, raw in enumerate(bars_raw):
        row = _mapping(raw, f"bars[{index}]")
        start = _datetime(row, "bucket_start")
        bars.append(
            HistoricalBar(
                instrument_id=instrument_id,
                interval=CandleInterval(start=start, end=start + _ONE_MINUTE),
                open=Price(Decimal(_string(row, "open"))),
                high=Price(Decimal(_string(row, "high"))),
                low=Price(Decimal(_string(row, "low"))),
                close=Price(Decimal(_string(row, "close"))),
                volume=_integer(row, "volume"),
                quality=CandleQuality(_string(row, "quality")),
                source_provider=_string(row, "source_provider"),
                source_record_count=_integer(row, "source_record_count"),
                provider_timestamp_raw=_optional_string(
                    row.get("provider_timestamp_raw"),
                    f"bars[{index}].provider_timestamp_raw",
                ),
                provider_timestamp_interpreted=(
                    None
                    if row.get("provider_timestamp_interpreted") is None
                    else _parse_datetime(
                        row["provider_timestamp_interpreted"],
                        f"bars[{index}].provider_timestamp_interpreted",
                    )
                ),
                canonicalisation_version=_string(row, "canonicalisation_version"),
            )
        )
    return HistoricalBarDataset(manifest=manifest, bars=tuple(bars))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Historical fixture {field} must be an object")
    return value


def _string(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Historical fixture {field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Historical fixture {field} must be a string or null")
    return value


def _integer(mapping: Mapping[str, object], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Historical fixture {field} must be an integer")
    return value


def _datetime(mapping: Mapping[str, object], field: str) -> datetime:
    return _parse_datetime(mapping.get(field), field)


def _parse_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Historical fixture {field} must be an ISO datetime string")
    parsed = datetime.fromisoformat(value)
    require_aware(parsed)
    return parsed


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Historical fixture {field} must be a list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Historical fixture {field} must be a list of strings")
        items.append(item)
    return items
