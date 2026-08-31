"""Broker-independent paper execution from accepted trigger evidence."""

from __future__ import annotations

from dataclasses import dataclass

from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.money import Quantity


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    """Immutable intent/fill facts produced from one accepted trigger event."""

    entry_intent: EntryIntent
    fill: Fill

    def __post_init__(self) -> None:
        if self.entry_intent.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("PaperExecutionResult requires PAPER EntryIntent")
        if self.fill.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("PaperExecutionResult requires PAPER Fill")
        if self.fill.entry_intent_id != self.entry_intent.entry_intent_id:
            raise ValueError("Fill must belong to the produced EntryIntent")
        if self.fill.trigger_event_id != self.entry_intent.trigger_event_id:
            raise ValueError("Fill and EntryIntent must reference the same TriggerEvent")


class PaperExecutionPort:
    """Deterministic in-memory PAPER implementation of the execution boundary."""

    def __init__(self) -> None:
        self._results: dict[str, PaperExecutionResult] = {}

    def execute(self, trigger_event: TriggerEvent, *, quantity: Quantity) -> PaperExecutionResult:
        """Create a PAPER intent/fill using the trigger's actual observed price.

        Reprocessing the same logical execution request returns the existing immutable
        facts. The configured/reference trigger price is retained as reference data;
        the simulated fill uses the actual observed eligible trigger-crossing price.
        """

        entry_intent = EntryIntent.create(
            trigger_event_id=trigger_event.trigger_event_id,
            signal_id=trigger_event.signal_id,
            instrument_id=trigger_event.instrument_id,
            reference_price=trigger_event.reference_price,
            quantity=quantity,
            execution_mode=ExecutionMode.PAPER,
            created_at=trigger_event.observed_at,
            run=trigger_event.run,
        )
        key = str(entry_intent.entry_intent_id)
        existing = self._results.get(key)
        if existing is not None:
            return existing

        fill = Fill.create(
            entry_intent_id=entry_intent.entry_intent_id,
            trigger_event_id=trigger_event.trigger_event_id,
            signal_id=trigger_event.signal_id,
            instrument_id=trigger_event.instrument_id,
            reference_price=trigger_event.reference_price,
            fill_price=trigger_event.observed_price,
            quantity=quantity,
            execution_mode=ExecutionMode.PAPER,
            filled_at=trigger_event.observed_at,
            run=trigger_event.run,
        )
        result = PaperExecutionResult(entry_intent=entry_intent, fill=fill)
        self._results[key] = result
        return result
