"""Provider-neutral canonical historical-bar research boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
from signalforge.domain.time import IST, CandleInterval, require_aware, to_utc
from signalforge.research.historical_grid import HistoricalBarGrid
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine
from signalforge.runtime.strategy import CompletedCandleStrategyContext, StrategyDecision

_ONE_MINUTE = timedelta(minutes=1)
_FIVE_MINUTES = timedelta(minutes=5)
_SESSION_OPEN = time(9, 15)  # Legacy NSE fixture coverage only.
_SESSION_END = time(15, 30)  # Never applied to explicit grids.


class CorporateActionPolicy(StrEnum):
    """Declared price/volume adjustment policy for one historical dataset."""

    RAW_UNADJUSTED = "raw_unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"
    DIVIDEND_ADJUSTED = "dividend_adjusted"
    NOT_APPLICABLE = "not_applicable"
    OTHER = "other"
    UNKNOWN = "unknown"


class HistoricalPriceBasis(StrEnum):
    """Economic price series represented by one historical dataset."""

    TRADED = "traded"
    MARK = "mark"
    INDEX = "index"
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
        start_utc = to_utc(self.interval.start)
        end_utc = to_utc(self.interval.end)
        if start_utc.second or start_utc.microsecond:
            raise ValueError("HistoricalBar start must align to an exact minute")
        if end_utc.second or end_utc.microsecond:
            raise ValueError("HistoricalBar end must align to an exact minute")
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
    expected_session_dates: tuple[date, ...]
    raw_row_count: int
    canonical_row_count: int
    missing_interval_count: int
    duplicate_observation_count: int
    corrupt_rejected_count: int
    corporate_action_policy: CorporateActionPolicy
    limitations: tuple[str, ...] = ()
    acquisition_evidence: tuple[str, ...] = ()
    grid: HistoricalBarGrid | None = None
    price_basis: HistoricalPriceBasis | None = None

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
        if self.expected_session_dates != tuple(sorted(set(self.expected_session_dates))):
            raise ValueError("Historical expected session dates must be unique and ordered")
        if self.grid is None and not self.expected_session_dates:
            raise ValueError("Legacy historical dataset requires expected session dates")
        grid = self.effective_grid
        if to_utc(self.requested_start) != grid.coverage[0].start or (
            to_utc(self.requested_end) != grid.coverage[-1].end
        ):
            if self.grid is None:
                raise ValueError(
                    "DATA-004 requested range must span complete declared regular NSE sessions"
                )
            raise ValueError("Historical requested range must match grid coverage bounds")
        if self.grid is not None and self.expected_session_dates:
            raise ValueError("Explicit historical grid must not also declare NSE sessions")
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

    @property
    def effective_grid(self) -> HistoricalBarGrid:
        """Resolve legacy NSE coverage without changing existing dataset identities."""
        if self.grid is not None:
            return self.grid
        return HistoricalBarGrid(
            grid_id="nse-regular-session",
            version="legacy-v1",
            coverage=tuple(
                CandleInterval(
                    datetime.combine(day, _SESSION_OPEN, tzinfo=IST),
                    datetime.combine(day, _SESSION_END, tzinfo=IST),
                )
                for day in self.expected_session_dates
            ),
        )

    def semantic_mapping(self) -> dict[str, object]:
        """Return interpretation provenance excluding operational acquisition time."""

        result = {
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
            "expected_session_dates": [
                session_date.isoformat() for session_date in self.expected_session_dates
            ],
            "canonical_row_count": self.canonical_row_count,
            "missing_interval_count": self.missing_interval_count,
            "corporate_action_policy": self.corporate_action_policy.value,
            "limitations": list(self.limitations),
        }
        if self.grid is not None:
            result["grid"] = self.grid.semantic_mapping()
        if self.price_basis is not None:
            result["price_basis"] = self.price_basis.value
        return result


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
            if not self.manifest.effective_grid.contains_minute(bar.interval.start):
                if self.manifest.grid is None:
                    raise ValueError(
                        "Historical bar session date is not declared by dataset manifest"
                    )
                raise ValueError("Historical bar interval is outside declared coverage grid")
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
        expected_raw_rows = (
            len(canonical)
            + duplicate_count
            + self.manifest.corrupt_rejected_count
        )
        if self.manifest.raw_row_count != expected_raw_rows:
            raise ValueError("Historical raw row count contradicts canonical dataset content")
        expected_missing = self.manifest.effective_grid.expected_minute_count - len(canonical)
        if self.manifest.missing_interval_count != expected_missing:
            raise ValueError("Historical missing interval count contradicts expected session grid")
        first = canonical[0].interval.start
        last = canonical[-1].interval.end
        if first != self.manifest.returned_start or last != self.manifest.returned_end:
            raise ValueError("Historical returned range contradicts canonical bar content")
        object.__setattr__(self, "bars", tuple(canonical))

    @classmethod
    def from_canonical_storage(
        cls,
        manifest: HistoricalDatasetManifest,
        bars: tuple[HistoricalBar, ...],
    ) -> HistoricalBarDataset:
        """Validate unique persisted bars while retaining source duplicate counts.

        Source duplicates were removed by normal canonicalization before storage.
        This does not reconstruct or fabricate upstream observations.
        """
        if manifest.raw_row_count != (
            manifest.canonical_row_count
            + manifest.duplicate_observation_count
            + manifest.corrupt_rejected_count
        ):
            raise ValueError("Stored historical raw counts contradict manifest")
        normalized = replace(
            manifest,
            duplicate_observation_count=0,
            raw_row_count=manifest.canonical_row_count + manifest.corrupt_rejected_count,
        )
        checked = cls(manifest=normalized, bars=bars)
        result = object.__new__(cls)
        object.__setattr__(result, "manifest", manifest)
        object.__setattr__(result, "bars", checked.bars)
        return result

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

class HistoricalContinuityError(RuntimeError):
    """Raised when a non-valid derived bucket prevents deterministic continuation."""

    def __init__(self, candle: CompletedCandle) -> None:
        self.candle = candle
        super().__init__(
            "Historical research continuity is unresolved at "
            f"{candle.interval.start.isoformat()} with quality={candle.quality.value}"
        )


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
    """Derive complete five-minute buckets from the declared coverage grid."""

    by_start = {bar.interval.start: bar for bar in dataset.bars}
    output: list[CompletedCandle] = []

    for interval in dataset.manifest.effective_grid.five_minute_intervals():
            bucket_start = interval.start
            expected_starts = tuple(
                bucket_start + minute * _ONE_MINUTE for minute in range(5)
            )
            constituents = tuple(
                by_start[start] for start in expected_starts if start in by_start
            )
            interval = CandleInterval(start=bucket_start, end=bucket_start + _FIVE_MINUTES)
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
        completed_count = 0

        derived = aggregate_one_minute_to_five_minute(dataset)
        for candle in derived:
            if candle.quality is CandleQuality.INCOMPLETE:
                incomplete += 1
                engine.break_continuity()
                raise HistoricalContinuityError(candle)
            if candle.quality is CandleQuality.MISSING:
                missing += 1
                engine.break_continuity()
                raise HistoricalContinuityError(candle)
            if candle.quality is not CandleQuality.VALID:
                raise ValueError("Unexpected historical derived candle quality")
            valid += 1

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
            decisions=tuple(decisions),
        )


def load_historical_bar_fixture(path: Path) -> HistoricalBarDataset:
    """Load one strict repository-local JSON historical-bar fixture."""

    return parse_historical_bar_fixture_json(path.read_text(encoding="utf-8"))


def parse_historical_bar_fixture_json(
    content: str, *, canonical_storage: bool = False
) -> HistoricalBarDataset:
    """Parse already-read historical fixture JSON without reopening any path."""

    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Historical fixture root must be an object")
    return parse_historical_bar_storage_payload(
        payload,
        canonical_storage=canonical_storage,
    )


def parse_historical_bar_storage_payload(
    payload: Mapping[str, object],
    *,
    canonical_storage: bool = False,
) -> HistoricalBarDataset:
    """Parse an already-materialized canonical historical storage payload."""

    manifest_raw = _mapping(payload.get("manifest"), "manifest")
    bars_raw = payload.get("bars")
    if not isinstance(bars_raw, list):
        raise ValueError("Historical fixture bars must be a list")

    if "grid" not in manifest_raw and "expected_session_dates" not in manifest_raw:
        raise ValueError("Legacy historical fixture requires expected_session_dates")
    if "grid" in manifest_raw and manifest_raw["grid"] is None:
        raise ValueError("Explicit historical grid must not be null")

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
        expected_session_dates=(
            tuple(_date_list(manifest_raw["expected_session_dates"], "expected_session_dates"))
            if "expected_session_dates" in manifest_raw
            else ()
        ),
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
        acquisition_evidence=tuple(
            _string_list(manifest_raw.get("acquisition_evidence"), "acquisition_evidence")
        ),
        grid=_parse_grid(manifest_raw.get("grid")),
        price_basis=(
            HistoricalPriceBasis(_string(manifest_raw, "price_basis"))
            if "price_basis" in manifest_raw
            else None
        ),
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
    if canonical_storage:
        return HistoricalBarDataset.from_canonical_storage(manifest, tuple(bars))
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


def _date_list(value: object, field: str) -> list[date]:
    if not isinstance(value, list):
        raise ValueError(f"Historical fixture {field} must be a list of ISO dates")
    items: list[date] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Historical fixture {field} must be a list of ISO dates")
        items.append(date.fromisoformat(item))
    return items


def _parse_grid(value: object) -> HistoricalBarGrid | None:
    """Parse optional explicit coverage while retaining legacy fixture compatibility."""
    if value is None:
        return None
    raw = _mapping(value, "grid")
    coverage_raw = raw.get("coverage")
    if not isinstance(coverage_raw, list):
        raise ValueError("Historical grid coverage must be an array")
    coverage = tuple(
        CandleInterval(
            start=_datetime(_mapping(item, "grid.coverage"), "start"),
            end=_datetime(_mapping(item, "grid.coverage"), "end"),
        )
        for item in coverage_raw
    )
    return HistoricalBarGrid(
        grid_id=_string(raw, "grid_id"),
        version=_string(raw, "version"),
        coverage=coverage,
    )
