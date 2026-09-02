from datetime import datetime

import pytest

from signalforge.domain.ids import ConfigId, FillId, RunId, SignalId
from signalforge.domain.position_outcomes import PositionOpenOutcome, PositionOpenOutcomeType
from signalforge.domain.provenance import RunIdentity, StrategyIdentity
from signalforge.domain.time import IST

AT = datetime(2026, 9, 2, 10, 0, tzinfo=IST)
SIGNAL_ID = SignalId("sf046-signal")


def _run() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("sf046-outcome-run"),
        strategy=StrategyIdentity("intraday_momentum_v1", "1.0.0"),
        config_id=ConfigId("sf046-outcome-config"),
        config_hash="sf046-outcome-hash",
        engine_calculation_version="engine-v1",
    )


def test_position_open_outcome_is_deterministic_per_run_and_fill() -> None:
    first = PositionOpenOutcome.create(
        fill_id=FillId("sf046-fill"),
        signal_id=SIGNAL_ID,
        decided_at=AT,
        outcome=PositionOpenOutcomeType.OPENED,
        run=_run(),
    )
    second = PositionOpenOutcome.create(
        fill_id=FillId("sf046-fill"),
        signal_id=SIGNAL_ID,
        decided_at=AT,
        outcome=PositionOpenOutcomeType.OPENED,
        run=_run(),
    )

    assert first == second


def test_position_open_outcome_identity_is_scoped_to_causal_run_and_fill() -> None:
    opened = PositionOpenOutcome.create(
        fill_id=FillId("sf046-fill"),
        signal_id=SIGNAL_ID,
        decided_at=AT,
        outcome=PositionOpenOutcomeType.OPENED,
        run=_run(),
    )
    rejected = PositionOpenOutcome.create(
        fill_id=opened.fill_id,
        signal_id=SignalId("sf046-other-signal"),
        decided_at=AT.replace(hour=11),
        outcome=PositionOpenOutcomeType.REJECTED_NON_POSITIVE_RISK,
        run=opened.run,
    )

    assert rejected.outcome_id == opened.outcome_id
    assert rejected != opened


def test_position_open_outcome_requires_an_aware_decision_timestamp() -> None:
    with pytest.raises(ValueError):
        PositionOpenOutcome.create(
            fill_id=FillId("sf046-fill"),
            signal_id=SIGNAL_ID,
            outcome=PositionOpenOutcomeType.OPENED,
            decided_at=datetime(2026, 9, 2, 10, 0),
            run=_run(),
        )
