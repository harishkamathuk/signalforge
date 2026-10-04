from datetime import datetime
from decimal import Decimal

from signalforge.config.rsi_mean_reversion_v1 import RsiMeanReversionV1Config
from signalforge.domain.ids import InstrumentId
from signalforge.domain.strategy import (
    DecisionReason,
    MomentumResult,
    SetupResult,
    StrategyEvaluation,
    TrendResult,
)
from signalforge.domain.time import IST, CandleInterval
from signalforge.runtime.decision_audit import (
    RSI_MEAN_REVERSION_DECISION_KIND,
    V1_DECISION_KIND,
    project_rsi_mean_reversion_decision,
    project_v1_decision,
)
from signalforge.runtime.eligibility import EvaluationGuardResult
from signalforge.runtime.rsi_mean_reversion_v1 import RsiMeanReversionDecision
from signalforge.runtime.strategy_evaluator import StrategyEvaluatorResult

INSTRUMENT = InstrumentId("NSE:DECISION")
INTERVAL = CandleInterval.five_minutes(datetime(2026, 10, 3, 10, 0, tzinfo=IST))


def test_v1_projection_preserves_historical_diagnostics() -> None:
    evaluation = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=INTERVAL,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )

    fact = project_v1_decision(evaluation)

    assert fact.decision_kind == V1_DECISION_KIND
    assert fact.qualified is True
    assert fact.actionable is True
    assert fact.reasons == ("qualified", "actionable")
    assert dict(fact.diagnostics) == {
        "adx_passed": True,
        "macd_signal_positive": None,
        "momentum_passed": True,
        "rsi_passed": True,
        "setup_passed": True,
        "trend_passed": True,
    }


def test_reference_projection_uses_decimal_text_without_v1_shape() -> None:
    decision = RsiMeanReversionDecision(
        instrument_id=INSTRUMENT,
        interval=INTERVAL,
        qualified=True,
        actionable=True,
        reasons=("rsi_below_threshold",),
        rsi14=Decimal("29.5000"),
    )

    fact = project_rsi_mean_reversion_decision(decision)

    assert fact.decision_kind == RSI_MEAN_REVERSION_DECISION_KIND
    assert dict(fact.diagnostics) == {"rsi14": "29.5", "rsi_ready": True}
    assert "trend_passed" not in fact.diagnostic_mapping


def test_reference_governance_status_remains_experimental() -> None:
    assert RsiMeanReversionV1Config().identify().status.value == "experimental"


def test_v1_projection_accepts_shared_runtime_result_without_changing_fact() -> None:
    evaluation = StrategyEvaluation(
        instrument_id=INSTRUMENT,
        interval=INTERVAL,
        trend=TrendResult(True),
        momentum=MomentumResult(True, True, True, None),
        setup=SetupResult(True),
        qualified=True,
        actionable=True,
        reasons=(DecisionReason.QUALIFIED, DecisionReason.ACTIONABLE),
    )
    runtime_result = StrategyEvaluatorResult(
        evaluation=evaluation,
        guard=EvaluationGuardResult(
            eligible=True,
            actionable=True,
            reasons=(),
        ),
    )

    assert project_v1_decision(runtime_result) == project_v1_decision(evaluation)
