"""Broker-independent trigger and execution domain facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from signalforge.domain.ids import (
    EntryIntentId,
    FillId,
    InstrumentId,
    SignalId,
    TriggerEventId,
    deterministic_id,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.time import require_aware


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class TriggerEvent:
    """Immutable evidence that an observed trade crossed an armed trigger."""

    trigger_event_id: TriggerEventId
    signal_id: SignalId
    instrument_id: InstrumentId
    reference_price: Price
    observed_price: Price
    observed_at: datetime
    run: RunIdentity

    def __post_init__(self) -> None:
        require_aware(self.observed_at)
        if self.reference_price.value <= 0 or self.observed_price.value <= 0:
            raise ValueError("TriggerEvent prices must be strictly positive")
        if self.observed_price.value < self.reference_price.value:
            raise ValueError("TriggerEvent observed_price must meet or exceed reference_price")
        if self.trigger_event_id != self.expected_id():
            raise ValueError("TriggerEvent ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        signal_id: SignalId,
        instrument_id: InstrumentId,
        reference_price: Price,
        observed_price: Price,
        observed_at: datetime,
        run: RunIdentity,
    ) -> TriggerEvent:
        event_id = deterministic_id(
            TriggerEventId,
            str(run.run_id),
            str(signal_id),
            observed_at.isoformat(),
            str(observed_price.value),
        )
        return cls(
            trigger_event_id=event_id,
            signal_id=signal_id,
            instrument_id=instrument_id,
            reference_price=reference_price,
            observed_price=observed_price,
            observed_at=observed_at,
            run=run,
        )

    def expected_id(self) -> TriggerEventId:
        return deterministic_id(
            TriggerEventId,
            str(self.run.run_id),
            str(self.signal_id),
            self.observed_at.isoformat(),
            str(self.observed_price.value),
        )


@dataclass(frozen=True, slots=True)
class EntryIntent:
    """Immutable request to execute an entry after a trigger event."""

    entry_intent_id: EntryIntentId
    trigger_event_id: TriggerEventId
    signal_id: SignalId
    instrument_id: InstrumentId
    reference_price: Price
    quantity: Quantity
    execution_mode: ExecutionMode
    created_at: datetime
    run: RunIdentity

    def __post_init__(self) -> None:
        require_aware(self.created_at)
        if self.reference_price.value <= 0:
            raise ValueError("EntryIntent reference_price must be strictly positive")
        if self.entry_intent_id != self.expected_id():
            raise ValueError("EntryIntent ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        trigger_event_id: TriggerEventId,
        signal_id: SignalId,
        instrument_id: InstrumentId,
        reference_price: Price,
        quantity: Quantity,
        execution_mode: ExecutionMode,
        created_at: datetime,
        run: RunIdentity,
    ) -> EntryIntent:
        intent_id = deterministic_id(
            EntryIntentId,
            str(run.run_id),
            str(trigger_event_id),
            str(instrument_id),
            str(quantity.value),
            execution_mode.value,
        )
        return cls(
            entry_intent_id=intent_id,
            trigger_event_id=trigger_event_id,
            signal_id=signal_id,
            instrument_id=instrument_id,
            reference_price=reference_price,
            quantity=quantity,
            execution_mode=execution_mode,
            created_at=created_at,
            run=run,
        )

    def expected_id(self) -> EntryIntentId:
        return deterministic_id(
            EntryIntentId,
            str(self.run.run_id),
            str(self.trigger_event_id),
            str(self.instrument_id),
            str(self.quantity.value),
            self.execution_mode.value,
        )


@dataclass(frozen=True, slots=True)
class Fill:
    """Immutable actual execution fact distinct from trigger/reference price."""

    fill_id: FillId
    entry_intent_id: EntryIntentId
    trigger_event_id: TriggerEventId
    signal_id: SignalId
    instrument_id: InstrumentId
    reference_price: Price
    fill_price: Price
    quantity: Quantity
    execution_mode: ExecutionMode
    filled_at: datetime
    run: RunIdentity

    def __post_init__(self) -> None:
        require_aware(self.filled_at)
        if self.reference_price.value <= 0 or self.fill_price.value <= 0:
            raise ValueError("Fill prices must be strictly positive")
        if self.fill_id != self.expected_id():
            raise ValueError("Fill ID does not match deterministic logical identity")

    @classmethod
    def create(
        cls,
        *,
        entry_intent_id: EntryIntentId,
        trigger_event_id: TriggerEventId,
        signal_id: SignalId,
        instrument_id: InstrumentId,
        reference_price: Price,
        fill_price: Price,
        quantity: Quantity,
        execution_mode: ExecutionMode,
        filled_at: datetime,
        run: RunIdentity,
    ) -> Fill:
        fill_id = deterministic_id(
            FillId,
            str(run.run_id),
            str(entry_intent_id),
            filled_at.isoformat(),
            str(fill_price.value),
            str(quantity.value),
        )
        return cls(
            fill_id=fill_id,
            entry_intent_id=entry_intent_id,
            trigger_event_id=trigger_event_id,
            signal_id=signal_id,
            instrument_id=instrument_id,
            reference_price=reference_price,
            fill_price=fill_price,
            quantity=quantity,
            execution_mode=execution_mode,
            filled_at=filled_at,
            run=run,
        )

    def expected_id(self) -> FillId:
        return deterministic_id(
            FillId,
            str(self.run.run_id),
            str(self.entry_intent_id),
            self.filled_at.isoformat(),
            str(self.fill_price.value),
            str(self.quantity.value),
        )
