import inspect
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import signalforge.runtime.indicator_recovery as indicator_recovery_module

from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import IndicatorRequirements, RsiRequirement
from signalforge.domain.market import CandleQuality, CompletedCandle
from signalforge.domain.money import Price
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.indicator_recovery import (
    IndicatorRecoveryError,
    IndicatorRecoveryReconciler,
    RecoveryCandle,
)
from signalforge.runtime.indicators import (
    V1_INDICATOR_REQUIREMENTS,
    IndicatorContinuity,
    IndicatorEngine,
)

INSTRUMENT = InstrumentId("NSE:SF050")
VERSION = "engine-v1"
START = datetime(2026, 9, 28, 9, 15, tzinfo=IST)


def _candle(
    index: int,
    *,
    start: datetime | None = None,
    instrument_id: InstrumentId = INSTRUMENT,
    quality: CandleQuality = CandleQuality.VALID,
) -> CompletedCandle:
    interval = CandleInterval.five_minutes(start or (START + timedelta(minutes=5 * index)))
    if quality is CandleQuality.MISSING:
        return CompletedCandle(
            instrument_id=instrument_id,
            interval=interval,
            quality=quality,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            source="sf050-unit",
            source_event_count=0,
        )
    base = Decimal("100") + Decimal(index) / Decimal("7")
    return CompletedCandle(
        instrument_id=instrument_id,
        interval=interval,
        quality=quality,
        open=Price(base),
        high=Price(base + Decimal("1.1")),
        low=Price(base - Decimal("0.9")),
        close=Price(base + Decimal("0.123456789012345678")),
        volume=1000 + index,
        source="sf050-unit",
        source_event_count=1,
    )


def _checkpoint(*, split: int, requirements=V1_INDICATOR_REQUIREMENTS):
    engine = IndicatorEngine(INSTRUMENT, VERSION, requirements=requirements)
    for index in range(split):
        engine.update(_candle(index))
    return engine.state


def test_zero_candle_recovery_restores_checkpoint_exactly() -> None:
    checkpoint = _checkpoint(split=20)

    recovery = IndicatorRecoveryReconciler(checkpoint)

    assert recovery.reconcile(()) == ()
    assert recovery.state == checkpoint


@pytest.mark.parametrize("split", (5, 25, 32, 49, 55))
def test_multi_candle_recovery_matches_uninterrupted_full_state(split: int) -> None:
    total = 65
    uninterrupted = IndicatorEngine(
        INSTRUMENT, VERSION, requirements=V1_INDICATOR_REQUIREMENTS
    )
    expected = [uninterrupted.update(_candle(index)) for index in range(total)]
    checkpoint = _checkpoint(split=split)
    recovery = IndicatorRecoveryReconciler(checkpoint)

    actual = recovery.reconcile(
        RecoveryCandle(_candle(index), continuity_ok=True)
        for index in range(split, total)
    )

    assert actual == tuple(expected[split:])
    assert recovery.state == uninterrupted.state


def test_rsi_only_recovery_remains_rsi_only() -> None:
    requirements = IndicatorRequirements.of(RsiRequirement(14))
    uninterrupted = IndicatorEngine(INSTRUMENT, VERSION, requirements=requirements)
    for index in range(20):
        uninterrupted.update(_candle(index))

    checkpoint = _checkpoint(split=10, requirements=requirements)
    recovery = IndicatorRecoveryReconciler(checkpoint)
    recovery.reconcile(
        RecoveryCandle(_candle(index), continuity_ok=True)
        for index in range(10, 20)
    )

    assert recovery.state == uninterrupted.state
    assert recovery.state.ema_states == ()
    assert recovery.state.adx_state is None
    assert recovery.state.macd_state is None
    assert recovery.state.rsi_state is not None


def test_persisted_broken_checkpoint_is_rejected() -> None:
    checkpoint = replace(
        _checkpoint(split=5),
        continuity=IndicatorContinuity.BROKEN,
    )

    with pytest.raises(IndicatorRecoveryError, match="continuity is broken"):
        IndicatorRecoveryReconciler(checkpoint)


def test_checkpoint_interval_cannot_be_reapplied() -> None:
    checkpoint = _checkpoint(split=5)
    recovery = IndicatorRecoveryReconciler(checkpoint)
    before = recovery.state.completed_candle_count

    with pytest.raises(IndicatorRecoveryError, match="strictly after"):
        recovery.reconcile((RecoveryCandle(_candle(4), continuity_ok=True),))

    assert recovery.state.completed_candle_count == before
    assert recovery.state.continuity is IndicatorContinuity.BROKEN


def test_unproven_gap_breaks_recovery_without_advancing() -> None:
    checkpoint = _checkpoint(split=5)
    recovery = IndicatorRecoveryReconciler(checkpoint)
    before = recovery.state.completed_candle_count
    skipped = _candle(6)

    with pytest.raises(IndicatorRecoveryError, match="cannot prove candle continuity"):
        recovery.reconcile((RecoveryCandle(skipped, continuity_ok=False),))

    assert recovery.state.completed_candle_count == before
    assert recovery.state.continuity is IndicatorContinuity.BROKEN


def test_authoritatively_valid_cross_session_gap_can_continue() -> None:
    friday = datetime(2026, 10, 2, 15, 25, tzinfo=IST)
    monday = datetime(2026, 10, 5, 9, 15, tzinfo=IST)
    source = IndicatorEngine(INSTRUMENT, VERSION, requirements=V1_INDICATOR_REQUIREMENTS)
    source.update(_candle(0, start=friday))
    checkpoint = source.state
    expected = source.update(_candle(1, start=monday))
    recovery = IndicatorRecoveryReconciler(checkpoint)

    actual = recovery.reconcile(
        (RecoveryCandle(_candle(1, start=monday), continuity_ok=True),)
    )

    assert actual == (expected,)
    assert recovery.state == source.state
    assert recovery.state.continuity is IndicatorContinuity.HEALTHY


def test_wrong_instrument_fails_closed_without_advancing() -> None:
    checkpoint = _checkpoint(split=5)
    recovery = IndicatorRecoveryReconciler(checkpoint)
    before = recovery.state.completed_candle_count

    with pytest.raises(IndicatorRecoveryError, match="instrument contradicts"):
        recovery.reconcile(
            (
                RecoveryCandle(
                    _candle(5, instrument_id=InstrumentId("NSE:OTHER")),
                    continuity_ok=True,
                ),
            )
        )

    assert recovery.state.completed_candle_count == before
    assert recovery.state.continuity is IndicatorContinuity.BROKEN


def test_invalid_canonical_candle_fails_closed() -> None:
    checkpoint = _checkpoint(split=5)
    recovery = IndicatorRecoveryReconciler(checkpoint)
    before = recovery.state.completed_candle_count

    with pytest.raises(IndicatorRecoveryError, match="Invalid candle quality"):
        recovery.reconcile(
            (RecoveryCandle(_candle(5, quality=CandleQuality.MISSING), continuity_ok=True),)
        )

    assert recovery.state.completed_candle_count == before
    assert recovery.state.continuity is IndicatorContinuity.BROKEN


def test_shared_recovery_module_has_no_strategy_or_lifecycle_dependency() -> None:
    """Keep SF-050 reconciliation below strategy/lifecycle orchestration."""

    source = inspect.getsource(indicator_recovery_module)
    for forbidden in (
        "IntradayMomentumV1Strategy",
        "RsiMeanReversionV1Strategy",
        "StrategyDecisionFact",
        "LifecycleCoordinator",
        "ReplayRuntime",
        "V1_INDICATOR_REQUIREMENTS",
    ):
        assert forbidden not in source
