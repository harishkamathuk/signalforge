"""Canonical preparation and suitability rules for run-independent indicator state."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256

from signalforge.adapters.openalgo.history import HistoricalCompletedCandle
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorRequirements
from signalforge.domain.prepared_indicators import (
    PreparedIndicatorCheckpoint,
    prepared_checkpoint_id,
)
from signalforge.domain.time import IST, CandleInterval, require_aware
from signalforge.domain.trading_calendar import NseEquityTradingCalendar
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngine

MINIMUM_STRATEGY_V1_COMPLETED_CANDLES = 250
NSE_FIVE_MINUTE_BARS_PER_REGULAR_SESSION = 75


def required_strategy_v1_warmup(configured_minimum: int) -> int:
    """Return configured Strategy V1 warm-up while preserving the canonical 250 floor."""

    if isinstance(configured_minimum, bool) or not isinstance(configured_minimum, int):
        raise TypeError("configured Strategy V1 warm-up must be an integer")
    if configured_minimum < 0:
        raise ValueError("configured Strategy V1 warm-up must not be negative")
    return max(MINIMUM_STRATEGY_V1_COMPLETED_CANDLES, configured_minimum)


class PreparedStateFailureCode(StrEnum):
    PREPARED_STATE_MISSING = "PREPARED_STATE_MISSING"
    PREPARED_STATE_STALE_SESSION = "PREPARED_STATE_STALE_SESSION"
    PREPARED_STATE_IDENTITY_MISMATCH = "PREPARED_STATE_IDENTITY_MISMATCH"
    PREPARED_STATE_NOT_READY = "PREPARED_STATE_NOT_READY"
    PREPARED_STATE_CONTINUITY_BROKEN = "PREPARED_STATE_CONTINUITY_BROKEN"
    PREPARED_STATE_PROVENANCE_INVALID = "PREPARED_STATE_PROVENANCE_INVALID"


class PreparedStateError(RuntimeError):
    """Explicit live-start readiness failure with a stable operator classification."""

    def __init__(self, code: PreparedStateFailureCode, detail: str) -> None:
        self.code = code
        super().__init__(detail)


class PreparationOutcome(StrEnum):
    READY_EXISTING = "READY_EXISTING"
    PREPARED_NEW = "PREPARED_NEW"


@dataclass(frozen=True, slots=True)
class PreparationResult:
    outcome: PreparationOutcome
    checkpoint: PreparedIndicatorCheckpoint


def previous_session_final_interval(
    target_trading_date: date,
    *,
    calendar: NseEquityTradingCalendar | None = None,
) -> CandleInterval:
    selected = calendar or NseEquityTradingCalendar()
    previous = selected.previous_trading_day(target_trading_date)
    return CandleInterval(
        datetime.combine(previous, time(15, 25), tzinfo=IST),
        datetime.combine(previous, time(15, 30), tzinfo=IST),
    )


def require_suitable_prepared_checkpoint(
    checkpoint: PreparedIndicatorCheckpoint | None,
    *,
    target_trading_date: date,
    instrument_id: InstrumentId,
    requirements: IndicatorRequirements,
    calculation_version: str,
    minimum_warmup_candles: int = MINIMUM_STRATEGY_V1_COMPLETED_CANDLES,
    calendar: NseEquityTradingCalendar | None = None,
) -> PreparedIndicatorCheckpoint:
    """Return a suitable checkpoint or raise one explicit readiness classification."""

    if checkpoint is None:
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_MISSING,
            "no prepared indicator checkpoint exists for the required market boundary",
        )
    if (
        checkpoint.instrument_id != instrument_id
        or checkpoint.state.requirements != requirements
        or checkpoint.state.calculation_version != calculation_version
        or checkpoint.exchange != "NSE"
    ):
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_IDENTITY_MISMATCH,
            "prepared indicator checkpoint identity is incompatible with live startup",
        )
    if checkpoint.state.continuity is not IndicatorContinuity.HEALTHY:
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_CONTINUITY_BROKEN,
            "prepared indicator checkpoint continuity is not HEALTHY",
        )
    required_warmup = required_strategy_v1_warmup(minimum_warmup_candles)
    if checkpoint.state.completed_candle_count < required_warmup:
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_NOT_READY,
            "prepared indicator checkpoint does not satisfy Strategy V1 warm-up "
            f"requirement of {required_warmup} completed candles",
        )
    expected = previous_session_final_interval(target_trading_date, calendar=calendar)
    if checkpoint.final_accepted_interval != expected or checkpoint.state.last_interval != expected:
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_STALE_SESSION,
            "prepared indicator checkpoint does not end at the immediately preceding NSE session",
        )
    if (
        checkpoint.target_trading_date != target_trading_date
        or checkpoint.requested_to != expected.start.date()
        or checkpoint.first_accepted_interval.start >= checkpoint.final_accepted_interval.end
    ):
        raise PreparedStateError(
            PreparedStateFailureCode.PREPARED_STATE_PROVENANCE_INVALID,
            "prepared indicator checkpoint provenance is internally inconsistent",
        )
    return checkpoint


def build_prepared_checkpoint(
    *,
    instrument_id: InstrumentId,
    requirements: IndicatorRequirements,
    calculation_version: str,
    target_trading_date: date,
    requested_from: date,
    requested_to: date,
    candles: Iterable[HistoricalCompletedCandle],
    prepared_at: datetime,
    minimum_warmup_candles: int = MINIMUM_STRATEGY_V1_COMPLETED_CANDLES,
    calendar: NseEquityTradingCalendar | None = None,
) -> PreparedIndicatorCheckpoint:
    """Validate historical bars, run canonical indicators, and create one immutable fact."""

    require_aware(prepared_at)
    selected_calendar = calendar or NseEquityTradingCalendar()
    expected_final = previous_session_final_interval(
        target_trading_date,
        calendar=selected_calendar,
    )
    accepted = tuple(candles)
    if not accepted:
        raise ValueError("historical preparation returned no accepted candles")
    if accepted[0].interval.start.astimezone(IST).date() < requested_from:
        raise ValueError("historical provider returned data before the requested range")
    if accepted[-1].interval.start.astimezone(IST).date() > requested_to:
        raise ValueError("historical provider returned data after the requested range")
    if requested_to != expected_final.start.date():
        raise ValueError("historical request must end on the immediately preceding trading session")
    _validate_candle_sequence(
        accepted,
        instrument_id=instrument_id,
        expected_final=expected_final,
        calendar=selected_calendar,
    )

    engine = IndicatorEngine(
        instrument_id,
        calculation_version,
        requirements=requirements,
    )
    for candle in accepted:
        engine.update(candle)
    state = engine.state
    if state.continuity is not IndicatorContinuity.HEALTHY:
        raise ValueError("historical preparation did not produce HEALTHY indicator continuity")
    required_warmup = required_strategy_v1_warmup(minimum_warmup_candles)
    if state.completed_candle_count < required_warmup:
        raise ValueError(
            "historical preparation produced fewer than "
            f"{required_warmup} required completed regular-session candles"
        )
    digest = canonical_candle_sequence_digest(accepted)
    return PreparedIndicatorCheckpoint(
        checkpoint_id=prepared_checkpoint_id(
            instrument_id=instrument_id,
            requirements=requirements,
            calculation_version=calculation_version,
            boundary=expected_final,
        ),
        state=state,
        exchange="NSE",
        target_trading_date=target_trading_date,
        historical_source="openalgo:/api/v1/history",
        requested_from=requested_from,
        requested_to=requested_to,
        first_accepted_interval=accepted[0].interval,
        final_accepted_interval=accepted[-1].interval,
        accepted_candle_count=len(accepted),
        candle_sequence_digest=digest,
        prepared_at=prepared_at,
    )


def canonical_candle_sequence_digest(candles: Iterable[HistoricalCompletedCandle]) -> str:
    rows = [
        {
            "instrument_id": str(candle.instrument_id),
            "start": candle.interval.start.isoformat(),
            "end": candle.interval.end.isoformat(),
            "open": str(candle.open.value),
            "high": str(candle.high.value),
            "low": str(candle.low.value),
            "close": str(candle.close.value),
            "volume": candle.volume,
            "source": candle.source,
        }
        for candle in candles
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def _validate_candle_sequence(
    candles: tuple[HistoricalCompletedCandle, ...],
    *,
    instrument_id: InstrumentId,
    expected_final: CandleInterval,
    calendar: NseEquityTradingCalendar,
) -> None:
    previous: HistoricalCompletedCandle | None = None
    by_date: dict[date, list[HistoricalCompletedCandle]] = {}
    for candle in candles:
        if candle.instrument_id != instrument_id:
            raise ValueError("historical candle instrument contradicts requested preparation")
        if candle.interval.end > expected_final.end:
            raise ValueError("historical preparation contains current/future-session data")
        if previous is not None and candle.interval.start < previous.interval.end:
            raise ValueError("historical preparation contains overlapping or out-of-order bars")
        previous = candle
        by_date.setdefault(candle.interval.start.astimezone(IST).date(), []).append(candle)

    first_date = candles[0].interval.start.astimezone(IST).date()
    final_date = expected_final.start.astimezone(IST).date()
    expected_days = calendar.trading_days(first_date, final_date)
    if tuple(sorted(by_date)) != expected_days:
        raise ValueError("historical preparation is missing one or more NSE trading sessions")

    for session_date in expected_days:
        rows = by_date[session_date]
        if len(rows) != NSE_FIVE_MINUTE_BARS_PER_REGULAR_SESSION:
            raise ValueError(
                "historical provider cannot prove complete 5-minute regular-session continuity"
            )
        expected_start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
        for index, candle in enumerate(rows):
            start = expected_start + timedelta(minutes=5 * index)
            if candle.interval != CandleInterval(start, start + timedelta(minutes=5)):
                raise ValueError(
                    "historical provider cannot prove complete 5-minute regular-session continuity"
                )

    if candles[-1].interval != expected_final:
        raise ValueError("historical preparation does not end at the previous NSE close boundary")
