"""Explicit Data Mappers between domain/runtime objects and SQLAlchemy records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from signalforge.domain.armed import ArmedSetup, ArmedSetupState, ExpiryReason
from signalforge.domain.audit import StateTransition, TransitionEntityType
from signalforge.domain.decision_facts import DecisionDiagnosticValue, StrategyDecisionFact
from signalforge.domain.execution import EntryIntent, ExecutionMode, Fill, TriggerEvent
from signalforge.domain.exits import Exit, ExitReason
from signalforge.domain.ids import (
    ConfigId,
    EntryIntentId,
    ExitId,
    FillId,
    InstrumentId,
    PositionId,
    PositionOpenOutcomeId,
    PreparedIndicatorCheckpointId,
    RunId,
    SignalId,
    StateTransitionId,
    TradeId,
    TriggerEventId,
)
from signalforge.domain.indicators import (
    AdxRequirement,
    EmaRequirement,
    IndicatorRequirement,
    IndicatorRequirements,
    MacdRequirement,
    RsiRequirement,
)
from signalforge.domain.money import Price, Quantity
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.positions import Position, PositionState
from signalforge.domain.prepared_indicators import PreparedIndicatorCheckpoint
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import CandleInterval
from signalforge.domain.trades import Trade, TradeState
from signalforge.persistence.models import (
    ArmedSetupRecord,
    EntryIntentRecord,
    ExitRecord,
    FillRecord,
    IndicatorCheckpointRecord,
    MarketInputCheckpointRecord,
    PositionOpenOutcomeRecord,
    PositionRecord,
    PreparedIndicatorCheckpointRecord,
    RunRecord,
    SignalRecord,
    StateTransitionRecord,
    StrategyConfigRecord,
    StrategyEvaluationRecord,
    TradeRecord,
    TriggerEventRecord,
)
from signalforge.runtime.adx import AdxState
from signalforge.runtime.candles import CandleEngineState
from signalforge.runtime.ema import EmaState
from signalforge.runtime.indicators import (
    V1_INDICATOR_REQUIREMENTS,
    IndicatorContinuity,
    IndicatorEngineState,
)
from signalforge.runtime.macd import MacdState
from signalforge.runtime.market_input import (
    CanonicalMarketInput,
    MarketInputCheckpoint,
)
from signalforge.runtime.rsi import RsiState


def market_input_checkpoint_record_from_domain(
    checkpoint: MarketInputCheckpoint,
) -> MarketInputCheckpointRecord:
    """Map restart-safe input progress and forming-candle state to persistence."""

    state = checkpoint.candle_state
    interval = state.active_interval
    payload: dict[str, object] = {
        "last_emitted_end": (
            None if state.last_emitted_end is None else state.last_emitted_end.isoformat()
        ),
        "active_interval_start": None if interval is None else interval.start.isoformat(),
        "active_interval_end": None if interval is None else interval.end.isoformat(),
        "source": state.source,
        "open": None if state.open is None else str(state.open.value),
        "high": None if state.high is None else str(state.high.value),
        "low": None if state.low is None else str(state.low.value),
        "close": None if state.close is None else str(state.close.value),
        "volume": state.volume,
        "source_event_count": state.source_event_count,
    }
    return MarketInputCheckpointRecord(
        run_id=str(checkpoint.run.run_id),
        instrument_id=str(checkpoint.instrument_id),
        source_id=checkpoint.last_input.source_id,
        sequence=checkpoint.last_input.sequence,
        source_event_id=checkpoint.last_input.source_event_id,
        payload_fingerprint=checkpoint.last_input.payload_fingerprint,
        candle_state_payload=payload,
        updated_at=checkpoint.updated_at,
    )


def market_input_checkpoint_from_record(
    record: MarketInputCheckpointRecord,
    run: RunIdentity,
) -> MarketInputCheckpoint:
    """Restore exact market-input progress and validated forming-candle state."""

    payload = record.candle_state_payload
    raw_start = payload.get("active_interval_start")
    raw_end = payload.get("active_interval_end")
    if (raw_start is None) != (raw_end is None):
        raise ValueError("Persisted CandleEngineState interval is incomplete")
    interval = None
    if raw_start is not None:
        if not isinstance(raw_start, str) or not isinstance(raw_end, str):
            raise ValueError("Persisted CandleEngineState interval is invalid")
        interval = CandleInterval(
            datetime.fromisoformat(raw_start),
            datetime.fromisoformat(raw_end),
        )

    raw_last_end = payload.get("last_emitted_end")
    if raw_last_end is not None and not isinstance(raw_last_end, str):
        raise ValueError("Persisted CandleEngineState last boundary is invalid")
    if raw_last_end is None:
        last_end = None
    else:
        last_end = datetime.fromisoformat(raw_last_end)

    def price_value(name: str) -> Price | None:
        raw = payload.get(name)
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ValueError(f"Persisted CandleEngineState {name} is invalid")
        return Price(Decimal(raw))

    raw_volume = payload.get("volume")
    if raw_volume is not None and (
        isinstance(raw_volume, bool) or not isinstance(raw_volume, int)
    ):
        raise ValueError("Persisted CandleEngineState volume is invalid")
    raw_count = payload.get("source_event_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise ValueError("Persisted CandleEngineState event count is invalid")
    raw_source = payload.get("source")
    if raw_source is not None and not isinstance(raw_source, str):
        raise ValueError("Persisted CandleEngineState source is invalid")

    state = CandleEngineState(
        instrument_id=InstrumentId(record.instrument_id),
        active_interval=interval,
        source=raw_source,
        open=price_value("open"),
        high=price_value("high"),
        low=price_value("low"),
        close=price_value("close"),
        volume=raw_volume,
        source_event_count=raw_count,
        last_emitted_end=last_end,
    )
    return MarketInputCheckpoint(
        run=run,
        instrument_id=InstrumentId(record.instrument_id),
        last_input=CanonicalMarketInput(
            source_id=record.source_id,
            sequence=record.sequence,
            source_event_id=record.source_event_id,
            payload_fingerprint=record.payload_fingerprint,
        ),
        candle_state=state,
        updated_at=record.updated_at,
    )


def strategy_config_record_from_domain(run: RunIdentity) -> StrategyConfigRecord:
    return StrategyConfigRecord(
        config_id=str(run.config_id),
        strategy_id=run.strategy.strategy_id,
        strategy_version=run.strategy.strategy_version,
        config_hash=run.config_hash,
    )


def run_record_from_domain(run: RunIdentity) -> RunRecord:
    return RunRecord(
        run_id=str(run.run_id),
        config_id=str(run.config_id),
        engine_calculation_version=run.engine_calculation_version,
    )


def run_identity_from_records(
    run: RunRecord,
    config: StrategyConfigRecord,
) -> RunIdentity:
    if run.config_id != config.config_id:
        raise ValueError("RunRecord and StrategyConfigRecord config identities do not match")
    return RunIdentity(
        run_id=RunId(run.run_id),
        strategy=StrategyIdentity(config.strategy_id, config.strategy_version),
        config_id=ConfigId(config.config_id),
        config_hash=config.config_hash,
        engine_calculation_version=run.engine_calculation_version,
    )


def strategy_decision_record_from_domain(
    run_id: RunId,
    fact: StrategyDecisionFact,
) -> StrategyEvaluationRecord:
    """Map a strategy-neutral immutable decision fact to persistence."""

    return StrategyEvaluationRecord(
        run_id=str(run_id),
        instrument_id=str(fact.instrument_id),
        interval_start=fact.interval.start,
        interval_end=fact.interval.end,
        decision_kind=fact.decision_kind,
        diagnostics=dict(fact.diagnostics),
        qualified=fact.qualified,
        actionable=fact.actionable,
        reasons=list(fact.reasons),
        trend_passed=None,
        momentum_passed=None,
        rsi_passed=None,
        adx_passed=None,
        macd_signal_positive=None,
        setup_passed=None,
    )


def strategy_decision_from_record(
    record: StrategyEvaluationRecord,
    strategy: StrategyIdentity,
) -> StrategyDecisionFact:
    """Hydrate a strategy-neutral decision fact from authoritative run provenance."""

    diagnostics: dict[str, DecisionDiagnosticValue] = {}
    for key, value in record.diagnostics.items():
        if not isinstance(value, (str, bool, int, type(None))):
            raise ValueError("Persisted strategy decision diagnostic has unsupported value")
        diagnostics[key] = value
    return StrategyDecisionFact.create(
        instrument_id=InstrumentId(record.instrument_id),
        interval=CandleInterval(record.interval_start, record.interval_end),
        strategy=strategy,
        decision_kind=record.decision_kind,
        qualified=record.qualified,
        actionable=record.actionable,
        reasons=tuple(record.reasons),
        diagnostics=diagnostics,
    )


def signal_record_from_domain(signal: Signal) -> SignalRecord:
    return SignalRecord(
        signal_id=str(signal.signal_id),
        run_id=str(signal.run.run_id),
        instrument_id=str(signal.instrument_id),
        interval_start=signal.interval.start,
        interval_end=signal.interval.end,
        signal_close=signal.signal_close.value,
        signal_low=signal.signal_low.value,
        created_at=signal.created_at,
    )


def signal_from_record(record: SignalRecord, run: RunIdentity) -> Signal:
    return Signal(
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        interval=CandleInterval(record.interval_start, record.interval_end),
        signal_close=Price(record.signal_close),
        signal_low=Price(record.signal_low),
        run=run,
        created_at=record.created_at,
    )


def armed_setup_record_from_domain(run_id: RunId, setup: ArmedSetup) -> ArmedSetupRecord:
    return ArmedSetupRecord(
        signal_id=str(setup.signal_id),
        run_id=str(run_id),
        raw_trigger=setup.raw_trigger.value,
        tradable_trigger=setup.tradable_trigger.value,
        signal_low=setup.signal_low.value,
        armed_at=setup.armed_at,
        valid_until=setup.valid_until,
        state=setup.state.value,
        terminal_at=setup.terminal_at,
        expiry_reason=None if setup.expiry_reason is None else setup.expiry_reason.value,
    )


def armed_setup_from_record(record: ArmedSetupRecord) -> ArmedSetup:
    return ArmedSetup(
        signal_id=SignalId(record.signal_id),
        raw_trigger=Price(record.raw_trigger),
        tradable_trigger=Price(record.tradable_trigger),
        signal_low=Price(record.signal_low),
        armed_at=record.armed_at,
        valid_until=record.valid_until,
        state=ArmedSetupState(record.state),
        terminal_at=record.terminal_at,
        expiry_reason=None if record.expiry_reason is None else ExpiryReason(record.expiry_reason),
    )


def trigger_event_record_from_domain(event: TriggerEvent) -> TriggerEventRecord:
    return TriggerEventRecord(
        trigger_event_id=str(event.trigger_event_id),
        signal_id=str(event.signal_id),
        run_id=str(event.run.run_id),
        instrument_id=str(event.instrument_id),
        reference_price=event.reference_price.value,
        observed_price=event.observed_price.value,
        observed_at=event.observed_at,
    )


def trigger_event_from_record(record: TriggerEventRecord, run: RunIdentity) -> TriggerEvent:
    return TriggerEvent(
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        observed_price=Price(record.observed_price),
        observed_at=record.observed_at,
        run=run,
    )


def entry_intent_record_from_domain(intent: EntryIntent) -> EntryIntentRecord:
    return EntryIntentRecord(
        entry_intent_id=str(intent.entry_intent_id),
        trigger_event_id=str(intent.trigger_event_id),
        signal_id=str(intent.signal_id),
        run_id=str(intent.run.run_id),
        instrument_id=str(intent.instrument_id),
        reference_price=intent.reference_price.value,
        quantity=intent.quantity.value,
        execution_mode=intent.execution_mode.value,
        created_at=intent.created_at,
    )


def entry_intent_from_record(record: EntryIntentRecord, run: RunIdentity) -> EntryIntent:
    return EntryIntent(
        entry_intent_id=EntryIntentId(record.entry_intent_id),
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        created_at=record.created_at,
        run=run,
    )


def fill_record_from_domain(fill: Fill) -> FillRecord:
    return FillRecord(
        fill_id=str(fill.fill_id),
        entry_intent_id=str(fill.entry_intent_id),
        trigger_event_id=str(fill.trigger_event_id),
        signal_id=str(fill.signal_id),
        run_id=str(fill.run.run_id),
        instrument_id=str(fill.instrument_id),
        reference_price=fill.reference_price.value,
        fill_price=fill.fill_price.value,
        quantity=fill.quantity.value,
        execution_mode=fill.execution_mode.value,
        filled_at=fill.filled_at,
    )


def fill_from_record(record: FillRecord, run: RunIdentity) -> Fill:
    return Fill(
        fill_id=FillId(record.fill_id),
        entry_intent_id=EntryIntentId(record.entry_intent_id),
        trigger_event_id=TriggerEventId(record.trigger_event_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        reference_price=Price(record.reference_price),
        fill_price=Price(record.fill_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        filled_at=record.filled_at,
        run=run,
    )


def trade_record_from_domain(trade: Trade) -> TradeRecord:
    return TradeRecord(
        trade_id=str(trade.trade_id),
        entry_fill_id=str(trade.entry_fill_id),
        signal_id=str(trade.signal_id),
        run_id=str(trade.run.run_id),
        instrument_id=str(trade.instrument_id),
        entry_price=trade.entry_price.value,
        stop_price=trade.stop_price.value,
        raw_target_price=trade.raw_target_price.value,
        tradable_target_price=trade.tradable_target_price.value,
        risk_per_share=trade.risk_per_share.value,
        quantity=trade.quantity.value,
        opened_at=trade.opened_at,
        state=trade.state.value,
        closed_at=trade.closed_at,
        exit_id=None if trade.exit_id is None else str(trade.exit_id),
    )


def trade_from_record(record: TradeRecord, run: RunIdentity) -> Trade:
    return Trade(
        trade_id=TradeId(record.trade_id),
        entry_fill_id=FillId(record.entry_fill_id),
        signal_id=SignalId(record.signal_id),
        instrument_id=InstrumentId(record.instrument_id),
        entry_price=Price(record.entry_price),
        stop_price=Price(record.stop_price),
        raw_target_price=Price(record.raw_target_price),
        tradable_target_price=Price(record.tradable_target_price),
        risk_per_share=Price(record.risk_per_share),
        quantity=Quantity(record.quantity),
        opened_at=record.opened_at,
        run=run,
        state=TradeState(record.state),
        closed_at=record.closed_at,
        exit_id=None if record.exit_id is None else ExitId(record.exit_id),
    )


def position_record_from_domain(position: Position) -> PositionRecord:
    return PositionRecord(
        position_id=str(position.position_id),
        trade_id=str(position.trade_id),
        run_id=str(position.run.run_id),
        instrument_id=str(position.instrument_id),
        quantity=position.quantity.value,
        average_entry_price=position.average_entry_price.value,
        opened_at=position.opened_at,
        state=position.state.value,
        closed_at=position.closed_at,
    )


def position_from_record(record: PositionRecord, run: RunIdentity) -> Position:
    return Position(
        position_id=PositionId(record.position_id),
        trade_id=TradeId(record.trade_id),
        instrument_id=InstrumentId(record.instrument_id),
        quantity=Quantity(record.quantity),
        average_entry_price=Price(record.average_entry_price),
        opened_at=record.opened_at,
        run=run,
        state=PositionState(record.state),
        closed_at=record.closed_at,
    )


def position_open_outcome_record_from_domain(
    outcome: PositionOpenOutcome,
) -> PositionOpenOutcomeRecord:
    return PositionOpenOutcomeRecord(
        outcome_id=str(outcome.outcome_id),
        fill_id=str(outcome.fill_id),
        signal_id=str(outcome.signal_id),
        run_id=str(outcome.run.run_id),
        outcome=outcome.outcome.value,
        decided_at=outcome.decided_at,
    )


def position_open_outcome_from_record(
    record: PositionOpenOutcomeRecord, run: RunIdentity
) -> PositionOpenOutcome:
    return PositionOpenOutcome(
        outcome_id=PositionOpenOutcomeId(record.outcome_id),
        fill_id=FillId(record.fill_id),
        signal_id=SignalId(record.signal_id),
        outcome=PositionOpenOutcomeType(record.outcome),
        decided_at=record.decided_at,
        run=run,
    )


def exit_record_from_domain(exit_fact: Exit) -> ExitRecord:
    return ExitRecord(
        exit_id=str(exit_fact.exit_id),
        exit_fill_id=str(exit_fact.exit_fill_id),
        trade_id=str(exit_fact.trade_id),
        position_id=str(exit_fact.position_id),
        run_id=str(exit_fact.run.run_id),
        instrument_id=str(exit_fact.instrument_id),
        reason=exit_fact.reason.value,
        reference_price=exit_fact.reference_price.value,
        fill_price=exit_fact.fill_price.value,
        quantity=exit_fact.quantity.value,
        execution_mode=exit_fact.execution_mode.value,
        exited_at=exit_fact.exited_at,
        realised_pnl=exit_fact.realised_pnl,
        realised_r=exit_fact.realised_r,
    )


def exit_from_record(record: ExitRecord, run: RunIdentity) -> Exit:
    return Exit(
        exit_id=ExitId(record.exit_id),
        exit_fill_id=FillId(record.exit_fill_id),
        trade_id=TradeId(record.trade_id),
        position_id=PositionId(record.position_id),
        instrument_id=InstrumentId(record.instrument_id),
        reason=ExitReason(record.reason),
        reference_price=Price(record.reference_price),
        fill_price=Price(record.fill_price),
        quantity=Quantity(record.quantity),
        execution_mode=ExecutionMode(record.execution_mode),
        exited_at=record.exited_at,
        realised_pnl=record.realised_pnl,
        realised_r=record.realised_r,
        run=run,
    )


def state_transition_record_from_domain(transition: StateTransition) -> StateTransitionRecord:
    return StateTransitionRecord(
        transition_id=str(transition.transition_id),
        run_id=str(transition.run.run_id),
        entity_type=transition.entity_type.value,
        entity_id=transition.entity_id,
        from_state=transition.from_state,
        to_state=transition.to_state,
        cause_type=transition.cause_type,
        cause_id=transition.cause_id,
        occurred_at=transition.occurred_at,
    )


def state_transition_from_record(
    record: StateTransitionRecord,
    run: RunIdentity,
) -> StateTransition:
    return StateTransition(
        transition_id=StateTransitionId(record.transition_id),
        entity_type=TransitionEntityType(record.entity_type),
        entity_id=record.entity_id,
        from_state=record.from_state,
        to_state=record.to_state,
        cause_type=record.cause_type,
        cause_id=record.cause_id,
        occurred_at=record.occurred_at,
        run=run,
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Indicator checkpoint decimal payload must be a string")
    return Decimal(value)


def _requirement_manifest(requirements: IndicatorRequirements) -> list[dict[str, object]]:
    manifest: list[dict[str, object]] = []
    for requirement in requirements.items:
        if isinstance(requirement, EmaRequirement):
            manifest.append({"kind": "ema", "period": requirement.period})
        elif isinstance(requirement, RsiRequirement):
            manifest.append({"kind": "rsi", "period": requirement.period})
        elif isinstance(requirement, AdxRequirement):
            manifest.append({"kind": "adx", "period": requirement.period})
        elif isinstance(requirement, MacdRequirement):
            manifest.append(
                {
                    "kind": "macd",
                    "fast_period": requirement.fast_period,
                    "slow_period": requirement.slow_period,
                    "signal_period": requirement.signal_period,
                }
            )
        else:
            raise TypeError(
                f"Unsupported indicator requirement type: {type(requirement).__name__}"
            )
    return manifest


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Indicator checkpoint integer payload must be an integer")
    return value


def _requirements_from_manifest(
    manifest: list[dict[str, object]],
) -> IndicatorRequirements:
    requirements: list[IndicatorRequirement] = []
    for item in manifest:
        kind = item.get("kind")
        if kind == "ema":
            requirements.append(EmaRequirement(_int_value(item["period"])))
        elif kind == "rsi":
            requirements.append(RsiRequirement(_int_value(item["period"])))
        elif kind == "adx":
            requirements.append(AdxRequirement(_int_value(item["period"])))
        elif kind == "macd":
            requirements.append(
                MacdRequirement(
                    _int_value(item["fast_period"]),
                    _int_value(item["slow_period"]),
                    _int_value(item["signal_period"]),
                )
            )
        else:
            raise ValueError(f"Unsupported indicator requirement kind in checkpoint: {kind}")
    return IndicatorRequirements(tuple(requirements))


def _ema_payload(state: EmaState) -> dict[str, object]:
    return {
        "period": state.period,
        "samples": state.samples,
        "value": _decimal_text(state.value),
        "seed_sum": _decimal_text(state.seed_sum),
    }


def _state_payload(state: IndicatorEngineState) -> dict[str, object]:
    rsi = state.rsi_state
    adx = state.adx_state
    macd = state.macd_state
    return {
        "emas": [_ema_payload(item) for item in state.ema_states],
        "rsi": None
        if rsi is None
        else {
            "samples": rsi.samples,
            "previous_close": _decimal_text(rsi.previous_close),
            "seed_gain_sum": _decimal_text(rsi.seed_gain_sum),
            "seed_loss_sum": _decimal_text(rsi.seed_loss_sum),
            "average_gain": _decimal_text(rsi.average_gain),
            "average_loss": _decimal_text(rsi.average_loss),
        },
        "adx": None
        if adx is None
        else {
            "samples": adx.samples,
            "previous_high": _decimal_text(adx.previous_high),
            "previous_low": _decimal_text(adx.previous_low),
            "previous_close": _decimal_text(adx.previous_close),
            "seed_tr_sum": _decimal_text(adx.seed_tr_sum),
            "seed_plus_dm_sum": _decimal_text(adx.seed_plus_dm_sum),
            "seed_minus_dm_sum": _decimal_text(adx.seed_minus_dm_sum),
            "smoothed_tr": _decimal_text(adx.smoothed_tr),
            "smoothed_plus_dm": _decimal_text(adx.smoothed_plus_dm),
            "smoothed_minus_dm": _decimal_text(adx.smoothed_minus_dm),
            "dx_seed_sum": _decimal_text(adx.dx_seed_sum),
            "dx_seed_count": adx.dx_seed_count,
            "adx": _decimal_text(adx.adx),
        },
        "macd": None
        if macd is None
        else {
            "samples": macd.samples,
            "fast_ema": _ema_payload(macd.fast_ema),
            "slow_ema": _ema_payload(macd.slow_ema),
            "signal_ema": _ema_payload(macd.signal_ema),
        },
    }


def _ema_from_payload(payload: dict[str, object]) -> EmaState:
    seed_sum = _decimal_value(payload["seed_sum"])
    assert seed_sum is not None
    return EmaState(
        _int_value(payload["period"]),
        _int_value(payload["samples"]),
        _decimal_value(payload.get("value")),
        seed_sum,
    )


def _state_from_payload(
    record: IndicatorCheckpointRecord,
    requirements: IndicatorRequirements,
) -> IndicatorEngineState:
    payload = record.state_payload
    if payload is None:
        raise ValueError("Indicator checkpoint state payload is missing")
    raw_emas = payload.get("emas")
    if not isinstance(raw_emas, list):
        raise ValueError("Indicator checkpoint EMA payload must be a list")
    ema_states = tuple(_ema_from_payload(item) for item in raw_emas if isinstance(item, dict))
    if len(ema_states) != len(raw_emas):
        raise ValueError("Indicator checkpoint EMA payload contains an invalid item")

    raw_rsi = payload.get("rsi")
    rsi_state = None
    if isinstance(raw_rsi, dict):
        gain_sum = _decimal_value(raw_rsi["seed_gain_sum"])
        loss_sum = _decimal_value(raw_rsi["seed_loss_sum"])
        assert gain_sum is not None and loss_sum is not None
        rsi_state = RsiState(
            _int_value(raw_rsi["samples"]),
            _decimal_value(raw_rsi.get("previous_close")),
            gain_sum,
            loss_sum,
            _decimal_value(raw_rsi.get("average_gain")),
            _decimal_value(raw_rsi.get("average_loss")),
        )
    elif raw_rsi is not None:
        raise ValueError("Indicator checkpoint RSI payload is invalid")

    raw_adx = payload.get("adx")
    adx_state = None
    if isinstance(raw_adx, dict):
        seed_tr = _decimal_value(raw_adx["seed_tr_sum"])
        seed_plus = _decimal_value(raw_adx["seed_plus_dm_sum"])
        seed_minus = _decimal_value(raw_adx["seed_minus_dm_sum"])
        dx_seed = _decimal_value(raw_adx["dx_seed_sum"])
        assert (
            seed_tr is not None
            and seed_plus is not None
            and seed_minus is not None
            and dx_seed is not None
        )
        adx_state = AdxState(
            _int_value(raw_adx["samples"]),
            _decimal_value(raw_adx.get("previous_high")),
            _decimal_value(raw_adx.get("previous_low")),
            _decimal_value(raw_adx.get("previous_close")),
            seed_tr,
            seed_plus,
            seed_minus,
            _decimal_value(raw_adx.get("smoothed_tr")),
            _decimal_value(raw_adx.get("smoothed_plus_dm")),
            _decimal_value(raw_adx.get("smoothed_minus_dm")),
            dx_seed,
            _int_value(raw_adx["dx_seed_count"]),
            _decimal_value(raw_adx.get("adx")),
        )
    elif raw_adx is not None:
        raise ValueError("Indicator checkpoint ADX payload is invalid")

    raw_macd = payload.get("macd")
    macd_state = None
    if isinstance(raw_macd, dict):
        fast = raw_macd.get("fast_ema")
        slow = raw_macd.get("slow_ema")
        signal = raw_macd.get("signal_ema")
        if not isinstance(fast, dict) or not isinstance(slow, dict) or not isinstance(signal, dict):
            raise ValueError("Indicator checkpoint MACD EMA payload is invalid")
        macd_state = MacdState(
            _int_value(raw_macd["samples"]),
            _ema_from_payload(fast),
            _ema_from_payload(slow),
            _ema_from_payload(signal),
        )
    elif raw_macd is not None:
        raise ValueError("Indicator checkpoint MACD payload is invalid")

    if record.last_interval_start is None:
        interval = None
    else:
        assert record.last_interval_end is not None
        interval = CandleInterval(record.last_interval_start, record.last_interval_end)
    state = IndicatorEngineState(
        InstrumentId(record.instrument_id),
        record.calculation_version,
        IndicatorContinuity(record.continuity_state),
        interval,
        requirements,
        ema_states,
        rsi_state,
        adx_state,
        macd_state,
    )
    # The relational count participates in optimistic checkpoint ordering while
    # the payload carries recursive component state. Recovery must reject a row
    # when those two authoritative representations disagree.
    if state.completed_candle_count != record.completed_candle_count:
        raise ValueError(
            "Indicator checkpoint completed-candle count contradicts component state"
        )
    return state


def indicator_checkpoint_record_from_state(
    run: RunIdentity, state: IndicatorEngineState
) -> IndicatorCheckpointRecord:
    """Map self-describing indicator state to its durable checkpoint record."""

    interval = state.last_interval
    legacy = state.requirements == V1_INDICATOR_REQUIREMENTS
    ema9 = state.ema_state(9) if legacy else None
    ema20 = state.ema_state(20) if legacy else None
    ema50 = state.ema_state(50) if legacy else None
    rsi = state.rsi_state if legacy else None
    adx = state.adx_state if legacy else None
    macd = state.macd_state if legacy else None
    return IndicatorCheckpointRecord(
        run_id=str(run.run_id),
        instrument_id=str(state.instrument_id),
        calculation_version=state.calculation_version,
        continuity_state=state.continuity.value,
        last_interval_start=None if interval is None else interval.start,
        last_interval_end=None if interval is None else interval.end,
        completed_candle_count=state.completed_candle_count,
        requirements_manifest=_requirement_manifest(state.requirements),
        state_payload=_state_payload(state),
        ema9_value=None if ema9 is None else ema9.value,
        ema9_seed_sum=None if ema9 is None else ema9.seed_sum,
        ema20_value=None if ema20 is None else ema20.value,
        ema20_seed_sum=None if ema20 is None else ema20.seed_sum,
        ema50_value=None if ema50 is None else ema50.value,
        ema50_seed_sum=None if ema50 is None else ema50.seed_sum,
        rsi_previous_close=None if rsi is None else rsi.previous_close,
        rsi_seed_gain_sum=None if rsi is None else rsi.seed_gain_sum,
        rsi_seed_loss_sum=None if rsi is None else rsi.seed_loss_sum,
        rsi_average_gain=None if rsi is None else rsi.average_gain,
        rsi_average_loss=None if rsi is None else rsi.average_loss,
        adx_previous_high=None if adx is None else adx.previous_high,
        adx_previous_low=None if adx is None else adx.previous_low,
        adx_previous_close=None if adx is None else adx.previous_close,
        adx_seed_tr_sum=None if adx is None else adx.seed_tr_sum,
        adx_seed_plus_dm_sum=None if adx is None else adx.seed_plus_dm_sum,
        adx_seed_minus_dm_sum=None if adx is None else adx.seed_minus_dm_sum,
        adx_smoothed_tr=None if adx is None else adx.smoothed_tr,
        adx_smoothed_plus_dm=None if adx is None else adx.smoothed_plus_dm,
        adx_smoothed_minus_dm=None if adx is None else adx.smoothed_minus_dm,
        adx_dx_seed_sum=None if adx is None else adx.dx_seed_sum,
        adx_dx_seed_count=None if adx is None else adx.dx_seed_count,
        adx=None if adx is None else adx.adx,
        macd_fast_value=None if macd is None else macd.fast_ema.value,
        macd_fast_seed_sum=None if macd is None else macd.fast_ema.seed_sum,
        macd_slow_value=None if macd is None else macd.slow_ema.value,
        macd_slow_seed_sum=None if macd is None else macd.slow_ema.seed_sum,
        macd_signal_value=None if macd is None else macd.signal_ema.value,
        macd_signal_seed_sum=None if macd is None else macd.signal_ema.seed_sum,
    )


def indicator_checkpoint_state_from_record(
    record: IndicatorCheckpointRecord,
) -> IndicatorEngineState:
    """Restore exact generic state, with compatibility for pre-SF-063 V1 rows."""

    if record.requirements_manifest is not None or record.state_payload is not None:
        if record.requirements_manifest is None or record.state_payload is None:
            raise ValueError("Indicator checkpoint generic manifest/payload must both be present")
        requirements = _requirements_from_manifest(record.requirements_manifest)
        return _state_from_payload(record, requirements)

    # Legacy M6 rows are an implicit fixed Strategy V1 checkpoint shape.
    samples = record.completed_candle_count
    if record.last_interval_start is None:
        interval = None
    else:
        assert record.last_interval_end is not None
        interval = CandleInterval(record.last_interval_start, record.last_interval_end)

    required = (
        record.ema9_seed_sum,
        record.ema20_seed_sum,
        record.ema50_seed_sum,
        record.rsi_seed_gain_sum,
        record.rsi_seed_loss_sum,
        record.adx_seed_tr_sum,
        record.adx_seed_plus_dm_sum,
        record.adx_seed_minus_dm_sum,
        record.adx_dx_seed_sum,
        record.adx_dx_seed_count,
        record.macd_fast_seed_sum,
        record.macd_slow_seed_sum,
        record.macd_signal_seed_sum,
    )
    if any(item is None for item in required):
        raise ValueError("Legacy Strategy V1 indicator checkpoint is incomplete")
    assert record.ema9_seed_sum is not None
    assert record.ema20_seed_sum is not None
    assert record.ema50_seed_sum is not None
    assert record.rsi_seed_gain_sum is not None
    assert record.rsi_seed_loss_sum is not None
    assert record.adx_seed_tr_sum is not None
    assert record.adx_seed_plus_dm_sum is not None
    assert record.adx_seed_minus_dm_sum is not None
    assert record.adx_dx_seed_sum is not None
    assert record.adx_dx_seed_count is not None
    assert record.macd_fast_seed_sum is not None
    assert record.macd_slow_seed_sum is not None
    assert record.macd_signal_seed_sum is not None

    ema9 = EmaState(9, samples, record.ema9_value, record.ema9_seed_sum)
    ema20 = EmaState(20, samples, record.ema20_value, record.ema20_seed_sum)
    ema50 = EmaState(50, samples, record.ema50_value, record.ema50_seed_sum)
    rsi = RsiState(
        samples,
        record.rsi_previous_close,
        record.rsi_seed_gain_sum,
        record.rsi_seed_loss_sum,
        record.rsi_average_gain,
        record.rsi_average_loss,
    )
    adx = AdxState(
        samples,
        record.adx_previous_high,
        record.adx_previous_low,
        record.adx_previous_close,
        record.adx_seed_tr_sum,
        record.adx_seed_plus_dm_sum,
        record.adx_seed_minus_dm_sum,
        record.adx_smoothed_tr,
        record.adx_smoothed_plus_dm,
        record.adx_smoothed_minus_dm,
        record.adx_dx_seed_sum,
        record.adx_dx_seed_count,
        record.adx,
    )
    macd = MacdState(
        samples,
        EmaState(12, samples, record.macd_fast_value, record.macd_fast_seed_sum),
        EmaState(26, samples, record.macd_slow_value, record.macd_slow_seed_sum),
        EmaState(9, max(0, samples - 25), record.macd_signal_value, record.macd_signal_seed_sum),
    )
    return IndicatorEngineState(
        InstrumentId(record.instrument_id),
        record.calculation_version,
        IndicatorContinuity(record.continuity_state),
        interval,
        V1_INDICATOR_REQUIREMENTS,
        tuple(
            {9: ema9, 20: ema20, 50: ema50}[requirement.period]
            for requirement in V1_INDICATOR_REQUIREMENTS.items
            if isinstance(requirement, EmaRequirement)
        ),
        rsi,
        adx,
        macd,
    )



def prepared_indicator_checkpoint_record_from_domain(
    checkpoint: PreparedIndicatorCheckpoint,
) -> PreparedIndicatorCheckpointRecord:
    """Map one immutable run-independent prepared indicator fact to persistence."""

    state = checkpoint.state
    interval = state.last_interval
    assert interval is not None
    return PreparedIndicatorCheckpointRecord(
        checkpoint_id=str(checkpoint.checkpoint_id),
        instrument_id=str(state.instrument_id),
        exchange=checkpoint.exchange,
        requirements_hash=checkpoint.requirements_hash,
        calculation_version=state.calculation_version,
        target_trading_date=checkpoint.target_trading_date,
        continuity_state=state.continuity.value,
        last_interval_start=interval.start,
        last_interval_end=interval.end,
        completed_candle_count=state.completed_candle_count,
        requirements_manifest=_requirement_manifest(state.requirements),
        state_payload=_state_payload(state),
        historical_source=checkpoint.historical_source,
        requested_from=checkpoint.requested_from,
        requested_to=checkpoint.requested_to,
        first_accepted_interval_start=checkpoint.first_accepted_interval.start,
        first_accepted_interval_end=checkpoint.first_accepted_interval.end,
        final_accepted_interval_start=checkpoint.final_accepted_interval.start,
        final_accepted_interval_end=checkpoint.final_accepted_interval.end,
        accepted_candle_count=checkpoint.accepted_candle_count,
        candle_sequence_digest=checkpoint.candle_sequence_digest,
        prepared_at=checkpoint.prepared_at,
    )


def prepared_indicator_checkpoint_from_record(
    record: PreparedIndicatorCheckpointRecord,
) -> PreparedIndicatorCheckpoint:
    """Restore one immutable prepared checkpoint using canonical state decoding."""

    requirements = _requirements_from_manifest(record.requirements_manifest)
    # Prepared and run-scoped checkpoint records intentionally share the exact
    # state-bearing field names consumed by the canonical checkpoint decoder.
    state = _state_from_payload(cast(IndicatorCheckpointRecord, record), requirements)
    checkpoint = PreparedIndicatorCheckpoint(
        checkpoint_id=PreparedIndicatorCheckpointId(record.checkpoint_id),
        state=state,
        exchange=record.exchange,
        target_trading_date=record.target_trading_date,
        historical_source=record.historical_source,
        requested_from=record.requested_from,
        requested_to=record.requested_to,
        first_accepted_interval=CandleInterval(
            record.first_accepted_interval_start,
            record.first_accepted_interval_end,
        ),
        final_accepted_interval=CandleInterval(
            record.final_accepted_interval_start,
            record.final_accepted_interval_end,
        ),
        accepted_candle_count=record.accepted_candle_count,
        candle_sequence_digest=record.candle_sequence_digest,
        prepared_at=record.prepared_at,
    )
    if record.requirements_hash != checkpoint.requirements_hash:
        raise ValueError(
            "Prepared indicator checkpoint requirements hash contradicts state manifest"
        )
    return checkpoint
