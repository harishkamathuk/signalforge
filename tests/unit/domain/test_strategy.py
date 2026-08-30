from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from signalforge.domain.ids import InstrumentId
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import CandleInterval

IST = ZoneInfo("Asia/Kolkata")


def _interval() -> CandleInterval:
    return CandleInterval.five_minutes(datetime(2026, 8, 28, 10, 0, tzinfo=IST))


def _evaluation(
    *,
    trend: bool = True,
    rsi: bool = True,
    adx: bool = True,
    setup: bool = True,
    actionable: bool = True,
    macd_signal_positive: bool | None = True,
) -> StrategyEvaluation:
    trend_result = TrendResult(trend)
    momentum_result = MomentumResult(
        passed=rsi and adx,
        rsi_passed=rsi,
        adx_passed=adx,
        macd_signal_positive=macd_signal_positive,
    )
    setup_result = SetupResult(setup)
    qualified = trend and rsi and adx and setup

    if qualified:
        reasons = (
            (DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE)
            if actionable
            else (DecisionReason.QUALIFIED, DecisionReason.QUALIFIED_NOT_ACTIONABLE)
        )
    else:
        reason_list: list[DecisionReason] = []
        if not trend:
            reason_list.append(DecisionReason.TREND_NOT_MET)
        if not (rsi and adx):
            reason_list.append(DecisionReason.MOMENTUM_NOT_MET)
        if not setup:
            reason_list.append(DecisionReason.SETUP_NOT_MET)
        reasons = tuple(reason_list)

    return StrategyEvaluation(
        instrument_id=InstrumentId("NSE:RELIANCE"),
        interval=_interval(),
        trend=trend_result,
        momentum=momentum_result,
        setup=setup_result,
        qualified=qualified,
        actionable=actionable if qualified else False,
        reasons=reasons,
    )


def test_qualified_actionable_evaluation_is_immutable() -> None:
    evaluation = _evaluation()

    assert evaluation.qualified is True
    assert evaluation.actionable is True
    assert evaluation.reasons == (DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE)

    with pytest.raises(FrozenInstanceError):
        evaluation.actionable = False  # type: ignore[misc]


def test_qualified_evaluation_may_be_non_actionable() -> None:
    evaluation = _evaluation(actionable=False)

    assert evaluation.qualified is True
    assert evaluation.actionable is False
    assert evaluation.reasons == (
        DecisionReason.QUALIFIED,
        DecisionReason.QUALIFIED_NOT_ACTIONABLE,
    )


def test_actionable_requires_qualified() -> None:
    with pytest.raises(ValueError, match="actionable requires qualified"):
        StrategyEvaluation(
            instrument_id=InstrumentId("NSE:RELIANCE"),
            interval=_interval(),
            trend=TrendResult(False),
            momentum=MomentumResult(True, True, True),
            setup=SetupResult(True),
            qualified=False,
            actionable=True,
            reasons=(DecisionReason.TREND_NOT_MET,),
        )


def test_qualification_must_equal_component_conjunction() -> None:
    with pytest.raises(ValueError, match="qualified must equal"):
        StrategyEvaluation(
            instrument_id=InstrumentId("NSE:RELIANCE"),
            interval=_interval(),
            trend=TrendResult(True),
            momentum=MomentumResult(True, True, True),
            setup=SetupResult(False),
            qualified=True,
            actionable=False,
            reasons=(DecisionReason.QUALIFIED, DecisionReason.QUALIFIED_NOT_ACTIONABLE),
        )


def test_failed_components_use_stable_reason_codes() -> None:
    evaluation = _evaluation(trend=False, rsi=False, setup=False)

    assert evaluation.qualified is False
    assert evaluation.reasons == (
        DecisionReason.TREND_NOT_MET,
        DecisionReason.MOMENTUM_NOT_MET,
        DecisionReason.SETUP_NOT_MET,
    )


def test_reasons_must_match_evaluation_state() -> None:
    with pytest.raises(ValueError, match="reasons do not match"):
        StrategyEvaluation(
            instrument_id=InstrumentId("NSE:RELIANCE"),
            interval=_interval(),
            trend=TrendResult(True),
            momentum=MomentumResult(True, True, True),
            setup=SetupResult(True),
            qualified=True,
            actionable=False,
            reasons=(DecisionReason.QUALIFIED,),
        )


def test_macd_metadata_cannot_change_v1_momentum_result() -> None:
    positive = _evaluation(macd_signal_positive=True)
    negative = _evaluation(macd_signal_positive=False)
    missing = _evaluation(macd_signal_positive=None)

    assert positive.momentum.passed is True
    assert negative.momentum.passed is True
    assert missing.momentum.passed is True
    assert positive.qualified == negative.qualified == missing.qualified is True


def test_momentum_passed_must_equal_rsi_and_adx() -> None:
    with pytest.raises(ValueError, match="must equal RSI AND ADX"):
        MomentumResult(
            passed=True,
            rsi_passed=True,
            adx_passed=False,
            macd_signal_positive=True,
        )


def test_result_booleans_are_strict() -> None:
    with pytest.raises(TypeError, match="TrendResult passed"):
        TrendResult(1)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="SetupResult passed"):
        SetupResult(1)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="macd_signal_positive"):
        MomentumResult(True, True, True, macd_signal_positive=1)  # type: ignore[arg-type]
