"""Read-only recovery bootstrap for persisted M6 state."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from signalforge.domain.armed import ArmedSetup, ArmedSetupState
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.execution import EntryIntent, Fill, TriggerEvent
from signalforge.domain.exits import Exit
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorRequirements
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.provenance import RunIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.errors import ContradictoryFactError
from signalforge.persistence.repositories import (
    PostgresArmedSetupRepository,
    PostgresEntryIntentRepository,
    PostgresExitRepository,
    PostgresFillRepository,
    PostgresIndicatorCheckpointRepository,
    PostgresPositionOpenOutcomeRepository,
    PostgresPositionRepository,
    PostgresRunProvenanceRepository,
    PostgresSignalRepository,
    PostgresStateTransitionRepository,
    PostgresTradeRepository,
    PostgresTriggerEventRepository,
)
from signalforge.runtime.indicators import IndicatorContinuity, IndicatorEngineState


class RecoveryDisposition(StrEnum):
    NEW = "new"
    RESUMABLE = "resumable"


@dataclass(frozen=True, slots=True)
class RecoveredLifecycle:
    setup: ArmedSetup | None
    signal: Signal | None
    trigger: TriggerEvent | None
    intent: EntryIntent | None
    fill: Fill | None
    outcome: PositionOpenOutcome | None
    trade: Trade | None
    position: Position | None
    exit_fact: Exit | None
    transitions: tuple[StateTransition, ...]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    disposition: RecoveryDisposition
    run: RunIdentity
    indicator_state: IndicatorEngineState | None
    lifecycle: RecoveredLifecycle


class RecoveryBootstrap:
    """Validate and rehydrate authoritative persisted runtime state."""

    def inspect(
        self,
        *,
        session: Session,
        requested_run: RunIdentity,
        instrument_id: InstrumentId,
        indicator_requirements: IndicatorRequirements,
    ) -> RecoveryResult:
        """Inspect persisted state without mutation.

        When indicator requirements are supplied, an existing checkpoint must
        match that exact canonical requirement set before it may be resumed.
        """
        run = PostgresRunProvenanceRepository(session).get(requested_run.run_id)
        signals = (
            PostgresSignalRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        setups = (
            PostgresArmedSetupRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        triggers = (
            PostgresTriggerEventRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        intents = (
            PostgresEntryIntentRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        fills = (
            PostgresFillRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        outcomes = (
            PostgresPositionOpenOutcomeRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        trades = (
            PostgresTradeRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        positions = (
            PostgresPositionRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        exits = (
            PostgresExitRepository(session).find_for_run_instrument(
                requested_run.run_id, instrument_id
            )
            if run
            else ()
        )
        checkpoint = (
            PostgresIndicatorCheckpointRepository(session).get(requested_run.run_id, instrument_id)
            if run
            else None
        )
        transitions = (
            PostgresStateTransitionRepository(session).find_for_run(requested_run.run_id)
            if run
            else ()
        )
        if run is None:
            return RecoveryResult(
                RecoveryDisposition.NEW,
                requested_run,
                None,
                RecoveredLifecycle(None, None, None, None, None, None, None, None, None, ()),
            )
        if run != requested_run:
            raise ContradictoryFactError("persisted run provenance differs from requested runtime")
        if any(item.run != run or item.instrument_id != instrument_id for item in signals):
            raise ContradictoryFactError("persisted signal lineage contradicts requested runtime")
        if checkpoint is not None and (
            checkpoint.instrument_id != instrument_id
            or checkpoint.calculation_version != requested_run.engine_calculation_version
        ):
            raise ContradictoryFactError(
                "persisted indicator checkpoint contradicts requested runtime"
            )
        if checkpoint is not None and checkpoint.requirements != indicator_requirements:
            raise ContradictoryFactError(
                "persisted indicator checkpoint requirements contradict requested strategy"
            )
        if checkpoint is not None and checkpoint.continuity is IndicatorContinuity.BROKEN:
            raise ContradictoryFactError("persisted indicator checkpoint continuity is broken")
        if len(outcomes) != len(fills):
            raise ContradictoryFactError("persisted fill lacks a completed position-open outcome")
        rejected_fill_ids = {
            item.fill_id
            for item in outcomes
            if item.outcome is PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK
        }
        if any(item.entry_fill_id in rejected_fill_ids for item in trades):
            raise ContradictoryFactError(
                "rejected open outcome conflicts with persisted trade for the same fill"
            )

        triggered_setups = tuple(
            item for item in setups if item.state is ArmedSetupState.TRIGGERED
        )
        for triggered_setup in triggered_setups:
            if any(item.signal_id == triggered_setup.signal_id for item in trades):
                continue
            matching_trigger = next(
                (item for item in triggers if item.signal_id == triggered_setup.signal_id),
                None,
            )
            matching_intent = next(
                (item for item in intents if item.signal_id == triggered_setup.signal_id),
                None,
            )
            matching_fill = next(
                (item for item in fills if item.signal_id == triggered_setup.signal_id),
                None,
            )
            matching_outcome = next(
                (item for item in outcomes if item.signal_id == triggered_setup.signal_id),
                None,
            )
            if matching_trigger is None or matching_intent is None:
                raise ContradictoryFactError(
                    "TRIGGERED setup lacks persisted trigger or entry intent"
                )
            if matching_fill is None:
                raise ContradictoryFactError(
                    "pending triggered entry cannot be resumed safely"
                )
            if (
                matching_outcome is None
                or matching_outcome.fill_id != matching_fill.fill_id
            ):
                raise ContradictoryFactError(
                    "TRIGGERED setup lacks completed position-open outcome"
                )
            if matching_outcome.outcome is PositionOpenOutcomeType.OPENED:
                raise ContradictoryFactError(
                    "opened entry outcome lacks persisted Trade and Position"
                )

        armed = tuple(item for item in setups if item.state is ArmedSetupState.ARMED)
        open_trades = tuple(item for item in trades if item.state is TradeState.OPEN)
        open_positions = tuple(item for item in positions if item.state is PositionState.OPEN)
        if len(armed) > 1 or len(open_trades) > 1 or len(open_positions) > 1:
            raise ContradictoryFactError("multiple active lifecycle graphs are not supported")
        if armed and (open_trades or open_positions):
            raise ContradictoryFactError("persisted ARMED and OPEN lifecycle states conflict")

        closed_trades = tuple(item for item in trades if item.state is TradeState.CLOSED)
        closed_positions = tuple(item for item in positions if item.state is PositionState.CLOSED)
        if bool(closed_trades) != bool(closed_positions) or len(closed_trades) != len(exits):
            raise ContradictoryFactError(
                "persisted CLOSED lifecycle lacks matching trade, position, or exit"
            )

        for closed_trade in closed_trades:
            matching_exit = next(
                (item for item in exits if item.trade_id == closed_trade.trade_id), None
            )
            if matching_exit is None or closed_trade.exit_id != matching_exit.exit_id:
                raise ContradictoryFactError("closed trade lacks a matching immutable exit")
            _require_close_transition(
                transitions,
                entity_type=TransitionEntityType.TRADE,
                entity_id=str(closed_trade.trade_id),
                exit_fact=matching_exit,
            )
        for closed_position in closed_positions:
            matching_exit = next(
                (item for item in exits if item.position_id == closed_position.position_id), None
            )
            if matching_exit is None:
                raise ContradictoryFactError("closed position lacks a matching immutable exit")
            _require_close_transition(
                transitions,
                entity_type=TransitionEntityType.POSITION,
                entity_id=str(closed_position.position_id),
                exit_fact=matching_exit,
            )

        if bool(open_trades) != bool(open_positions):
            raise ContradictoryFactError("persisted trade and position active states conflict")

        trade = open_trades[0] if open_trades else (closed_trades[0] if closed_trades else None)
        position = (
            open_positions[0]
            if open_positions
            else (closed_positions[0] if closed_positions else None)
        )

        active_setup = armed[0] if armed else None
        signal_id = (
            active_setup.signal_id
            if active_setup is not None
            else (trade.signal_id if trade is not None else None)
        )
        signal = next((item for item in signals if item.signal_id == signal_id), None)
        if signal_id is not None and signal is None:
            raise ContradictoryFactError("active lifecycle references a missing signal")

        setup = active_setup
        trigger = None
        intent = None
        fill = None
        outcome = None
        active_transitions: tuple[StateTransition, ...] = ()

        if active_setup is not None:
            _require_transition(
                transitions,
                entity_type=TransitionEntityType.ARMED_SETUP,
                entity_id=str(active_setup.signal_id),
                from_state="none",
                to_state=ArmedSetupState.ARMED.value,
            )
            if any(item.signal_id == active_setup.signal_id for item in triggers):
                raise ContradictoryFactError("ARMED setup conflicts with persisted trigger event")
            arm_transition = _require_transition(
                transitions,
                entity_type=TransitionEntityType.ARMED_SETUP,
                entity_id=str(active_setup.signal_id),
                from_state="none",
                to_state=ArmedSetupState.ARMED.value,
            )
            terminal_transitions = tuple(
                item
                for item in _matching_transitions(
                    transitions,
                    entity_type=TransitionEntityType.ARMED_SETUP,
                    entity_id=str(active_setup.signal_id),
                )
                if item.from_state == ArmedSetupState.ARMED.value
                and item.to_state
                in {
                    ArmedSetupState.TRIGGERED.value,
                    ArmedSetupState.EXPIRED.value,
                }
            )
            if terminal_transitions:
                raise ContradictoryFactError(
                    "persisted ARMED setup conflicts with terminal transition evidence"
                )
            active_transitions = (arm_transition,)

        if trade is not None and trade.state is TradeState.OPEN:
            if position is None or position.trade_id != trade.trade_id:
                raise ContradictoryFactError(
                    "OPEN lifecycle lacks a consistent Trade and Position"
                )
            fill = next((item for item in fills if item.fill_id == trade.entry_fill_id), None)
            if fill is None:
                raise ContradictoryFactError("trade references a missing persisted entry fill")
            outcome = next((item for item in outcomes if item.fill_id == fill.fill_id), None)
            if (
                outcome is None
                or outcome.outcome is not PositionOpenOutcomeType.OPENED
                or outcome.signal_id != trade.signal_id
            ):
                raise ContradictoryFactError(
                    "OPEN lifecycle lacks a consistent fill outcome and position"
                )
            intent = next(
                (item for item in intents if item.entry_intent_id == fill.entry_intent_id),
                None,
            )
            trigger = next(
                (item for item in triggers if item.trigger_event_id == fill.trigger_event_id),
                None,
            )
            setup = next((item for item in setups if item.signal_id == trade.signal_id), None)
            if setup is None or setup.state is not ArmedSetupState.TRIGGERED:
                raise ContradictoryFactError(
                    "OPEN lifecycle requires the matching TRIGGERED setup"
                )
            if signal is None or intent is None or trigger is None:
                raise ContradictoryFactError(
                    "OPEN lifecycle lacks complete persisted execution ancestry"
                )
            _validate_open_graph(
                run=run,
                instrument_id=instrument_id,
                signal=signal,
                setup=setup,
                trigger=trigger,
                intent=intent,
                fill=fill,
                outcome=outcome,
                trade=trade,
                position=position,
            )
            if any(
                item.entity_type is TransitionEntityType.ARMED_SETUP
                and item.entity_id == str(setup.signal_id)
                and item.from_state == ArmedSetupState.ARMED.value
                and item.to_state == ArmedSetupState.EXPIRED.value
                for item in transitions
            ):
                raise ContradictoryFactError(
                    "TRIGGERED setup conflicts with expiry transition evidence"
                )
            if any(
                item.entity_type is TransitionEntityType.TRADE
                and item.entity_id == str(trade.trade_id)
                and item.from_state == TradeState.OPEN.value
                and item.to_state == TradeState.CLOSED.value
                for item in transitions
            ):
                raise ContradictoryFactError(
                    "OPEN trade conflicts with close transition evidence"
                )
            if any(
                item.entity_type is TransitionEntityType.POSITION
                and item.entity_id == str(position.position_id)
                and item.from_state == PositionState.OPEN.value
                and item.to_state == PositionState.CLOSED.value
                for item in transitions
            ):
                raise ContradictoryFactError(
                    "OPEN position conflicts with close transition evidence"
                )

            required = (
                _require_transition(
                    transitions,
                    entity_type=TransitionEntityType.ARMED_SETUP,
                    entity_id=str(setup.signal_id),
                    from_state="none",
                    to_state=ArmedSetupState.ARMED.value,
                ),
                _require_transition(
                    transitions,
                    entity_type=TransitionEntityType.ARMED_SETUP,
                    entity_id=str(setup.signal_id),
                    from_state=ArmedSetupState.ARMED.value,
                    to_state=ArmedSetupState.TRIGGERED.value,
                    cause_type="trigger_event",
                    cause_id=str(trigger.trigger_event_id),
                ),
                _require_transition(
                    transitions,
                    entity_type=TransitionEntityType.TRADE,
                    entity_id=str(trade.trade_id),
                    from_state="none",
                    to_state=TradeState.OPEN.value,
                    cause_type="fill",
                    cause_id=str(fill.fill_id),
                ),
                _require_transition(
                    transitions,
                    entity_type=TransitionEntityType.POSITION,
                    entity_id=str(position.position_id),
                    from_state="none",
                    to_state=PositionState.OPEN.value,
                    cause_type="trade",
                    cause_id=str(trade.trade_id),
                ),
            )
            active_transitions = required
        elif trade is not None:
            outcome = next(
                (item for item in outcomes if item.fill_id == trade.entry_fill_id),
                None,
            )
            if (
                outcome is None
                or outcome.outcome is not PositionOpenOutcomeType.OPENED
                or position is None
                or position.trade_id != trade.trade_id
            ):
                raise ContradictoryFactError(
                    "CLOSED lifecycle lacks a consistent fill outcome and position"
                )

        exit_fact = exits[0] if len(exits) == 1 else None
        return RecoveryResult(
            RecoveryDisposition.RESUMABLE,
            run,
            checkpoint,
            RecoveredLifecycle(
                setup,
                signal,
                trigger,
                intent,
                fill,
                outcome,
                trade,
                position,
                exit_fact,
                active_transitions,
            ),
        )


def _matching_transitions(
    transitions: tuple[StateTransition, ...],
    *,
    entity_type: TransitionEntityType,
    entity_id: str,
) -> tuple[StateTransition, ...]:
    return tuple(
        item
        for item in transitions
        if item.entity_type is entity_type and item.entity_id == entity_id
    )


def _require_transition(
    transitions: tuple[StateTransition, ...],
    *,
    entity_type: TransitionEntityType,
    entity_id: str,
    from_state: str,
    to_state: str,
    cause_type: str | None = None,
    cause_id: str | None = None,
) -> StateTransition:
    matches = tuple(
        item
        for item in transitions
        if item.entity_type is entity_type
        and item.entity_id == entity_id
        and item.from_state == from_state
        and item.to_state == to_state
        and (cause_type is None or item.cause_type == cause_type)
        and (cause_id is None or item.cause_id == cause_id)
    )
    if len(matches) != 1:
        raise ContradictoryFactError("active lifecycle lacks required transition evidence")
    return matches[0]


def _validate_open_graph(
    *,
    run: RunIdentity,
    instrument_id: InstrumentId,
    signal: Signal,
    setup: ArmedSetup,
    trigger: TriggerEvent,
    intent: EntryIntent,
    fill: Fill,
    outcome: PositionOpenOutcome,
    trade: Trade,
    position: Position,
) -> None:
    if any(
        item_run != run
        for item_run in (
            signal.run,
            trigger.run,
            intent.run,
            fill.run,
            outcome.run,
            trade.run,
            position.run,
        )
    ):
        raise ContradictoryFactError("OPEN lifecycle facts contradict requested run provenance")
    if any(
        item_instrument != instrument_id
        for item_instrument in (
            signal.instrument_id,
            trigger.instrument_id,
            intent.instrument_id,
            fill.instrument_id,
            trade.instrument_id,
            position.instrument_id,
        )
    ):
        raise ContradictoryFactError("OPEN lifecycle facts contradict requested instrument")
    if (
        setup.signal_id != signal.signal_id
        or trigger.signal_id != signal.signal_id
        or intent.signal_id != signal.signal_id
        or fill.signal_id != signal.signal_id
        or outcome.signal_id != signal.signal_id
        or trade.signal_id != signal.signal_id
    ):
        raise ContradictoryFactError("OPEN lifecycle signal lineage is inconsistent")
    if trigger.reference_price != setup.tradable_trigger:
        raise ContradictoryFactError("trigger reference contradicts persisted setup")
    if (
        intent.trigger_event_id != trigger.trigger_event_id
        or fill.trigger_event_id != trigger.trigger_event_id
        or fill.entry_intent_id != intent.entry_intent_id
    ):
        raise ContradictoryFactError("OPEN lifecycle execution identifiers are inconsistent")
    if (
        intent.reference_price != trigger.reference_price
        or fill.reference_price != trigger.reference_price
        or intent.quantity != fill.quantity
        or intent.execution_mode != fill.execution_mode
    ):
        raise ContradictoryFactError("OPEN lifecycle execution facts are inconsistent")
    if (
        trade.entry_fill_id != fill.fill_id
        or trade.entry_price != fill.fill_price
        or trade.quantity != fill.quantity
        or position.trade_id != trade.trade_id
        or position.quantity != trade.quantity
        or position.average_entry_price != trade.entry_price
    ):
        raise ContradictoryFactError("OPEN lifecycle economic facts are inconsistent")


def _require_close_transition(
    transitions: tuple[StateTransition, ...],
    *,
    entity_type: TransitionEntityType,
    entity_id: str,
    exit_fact: Exit,
) -> None:
    matches = tuple(
        item
        for item in transitions
        if item.entity_type is entity_type
        and item.entity_id == entity_id
        and item.from_state == "open"
        and item.to_state == "closed"
    )
    if (
        len(matches) != 1
        or matches[0].cause_type != "exit"
        or matches[0].cause_id != str(exit_fact.exit_id)
    ):
        raise ContradictoryFactError("closed lifecycle lacks a matching close transition")
