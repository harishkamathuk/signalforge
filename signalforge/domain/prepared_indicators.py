"""Run-independent prepared indicator state for pre-session live readiness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256

from signalforge.domain.ids import (
    InstrumentId,
    PreparedIndicatorCheckpointId,
    deterministic_id,
)
from signalforge.domain.indicators import IndicatorRequirements
from signalforge.domain.time import CandleInterval, require_aware
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngineState


def indicator_requirements_hash(requirements: IndicatorRequirements) -> str:
    """Return a deterministic compatibility identity for indicator requirements."""

    return sha256("\x1f".join(requirements.keys).encode("utf-8")).hexdigest()


def prepared_checkpoint_id(
    *,
    instrument_id: InstrumentId,
    requirements: IndicatorRequirements,
    calculation_version: str,
    boundary: CandleInterval,
) -> PreparedIndicatorCheckpointId:
    """Identify one authoritative prepared-state fact independent of its derivation."""

    return deterministic_id(
        PreparedIndicatorCheckpointId,
        str(instrument_id),
        indicator_requirements_hash(requirements),
        calculation_version,
        boundary.start.astimezone(UTC).isoformat(),
        boundary.end.astimezone(UTC).isoformat(),
    )


@dataclass(frozen=True, slots=True)
class PreparedIndicatorCheckpoint:
    """Immutable indicator state prepared through one completed market boundary."""

    checkpoint_id: PreparedIndicatorCheckpointId
    state: IndicatorEngineState
    exchange: str
    target_trading_date: date
    historical_source: str
    requested_from: date
    requested_to: date
    first_accepted_interval: CandleInterval
    final_accepted_interval: CandleInterval
    accepted_candle_count: int
    candle_sequence_digest: str
    prepared_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.prepared_at)
        if self.exchange != "NSE":
            raise ValueError("M8 prepared indicator checkpoints support NSE only")
        if not self.historical_source.strip():
            raise ValueError("Prepared checkpoint historical_source must not be empty")
        if self.requested_to < self.requested_from:
            raise ValueError("Prepared checkpoint requested range is invalid")
        if self.accepted_candle_count <= 0:
            raise ValueError("Prepared checkpoint requires accepted historical candles")
        if self.accepted_candle_count > self.state.completed_candle_count:
            raise ValueError(
                "Prepared checkpoint accepted-candle count exceeds lifetime indicator count"
            )
        if len(self.candle_sequence_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.candle_sequence_digest
        ):
            raise ValueError("Prepared checkpoint candle digest must be lowercase SHA-256")
        if self.state.continuity is not IndicatorContinuity.HEALTHY:
            raise ValueError("Prepared checkpoint state must have HEALTHY continuity")
        if self.state.last_interval != self.final_accepted_interval:
            raise ValueError("Prepared checkpoint state boundary contradicts provenance")
        if self.first_accepted_interval.start > self.final_accepted_interval.start:
            raise ValueError("Prepared checkpoint accepted interval range is reversed")
        expected_id = prepared_checkpoint_id(
            instrument_id=self.state.instrument_id,
            requirements=self.state.requirements,
            calculation_version=self.state.calculation_version,
            boundary=self.final_accepted_interval,
        )
        if self.checkpoint_id != expected_id:
            raise ValueError("Prepared checkpoint identity contradicts logical boundary")

    @property
    def instrument_id(self) -> InstrumentId:
        return self.state.instrument_id

    @property
    def requirements_hash(self) -> str:
        return indicator_requirements_hash(self.state.requirements)
