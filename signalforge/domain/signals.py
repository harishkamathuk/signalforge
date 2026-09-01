"""Immutable qualifying-signal domain fact."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from signalforge.domain.identity import canonical_timestamp
from signalforge.domain.ids import InstrumentId, SignalId, deterministic_id
from signalforge.domain.money import Price
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import CandleInterval, require_aware


@dataclass(frozen=True, slots=True)
class Signal:
    """Immutable signal derived from an actionable strategy evaluation."""

    signal_id: SignalId
    instrument_id: InstrumentId
    interval: CandleInterval
    signal_close: Price
    signal_low: Price
    run: RunIdentity
    created_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.created_at)
        if self.signal_close.value <= 0:
            raise ValueError("Signal close must be strictly positive")
        if self.signal_low.value <= 0:
            raise ValueError("Signal low must be strictly positive")
        if self.signal_low.value > self.signal_close.value:
            raise ValueError("Signal low must not exceed signal close")
        if self.signal_id != self.expected_id():
            raise ValueError("Signal ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        instrument_id: InstrumentId,
        interval: CandleInterval,
        signal_close: Price,
        signal_low: Price,
        run: RunIdentity,
        created_at: datetime,
    ) -> Signal:
        """Create a signal with its deterministic identity derived from logical facts."""

        signal_id = deterministic_id(
            SignalId,
            str(run.run_id),
            str(instrument_id),
            canonical_timestamp(interval.start),
            canonical_timestamp(interval.end),
        )
        return cls(
            signal_id=signal_id,
            instrument_id=instrument_id,
            interval=interval,
            signal_close=signal_close,
            signal_low=signal_low,
            run=run,
            created_at=created_at,
        )

    def expected_id(self) -> SignalId:
        """Return the deterministic ID implied by the signal's logical identity."""

        return deterministic_id(
            SignalId,
            str(self.run.run_id),
            str(self.instrument_id),
            canonical_timestamp(self.interval.start),
            canonical_timestamp(self.interval.end),
        )
