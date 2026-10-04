from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from signalforge.config.strategy_registry import (
    StrategySelection,
    UnknownStrategyError,
)
from signalforge.domain.ids import InstrumentId
from signalforge.domain.instruments import TickSizeRule, TickSizeSchedule
from signalforge.domain.money import Price, Quantity
from signalforge.domain.time import IST
from signalforge.research.contracts import (
    DatasetDefinition,
    DatasetSourceDefinition,
    ExperimentDefinition,
    InstrumentExecutionDefinition,
    UniverseDefinition,
)

A = InstrumentId("NSE:AAA")
B = InstrumentId("NSE:BBB")
START = datetime(2026, 1, 1, 9, 15, tzinfo=IST)
END = datetime(2026, 1, 31, 15, 30, tzinfo=IST)


def _universe(*items: InstrumentId) -> UniverseDefinition:
    return UniverseDefinition(tuple(items))


def _dataset(
    sources: tuple[DatasetSourceDefinition, ...] | None = None,
    *,
    start_at: datetime = START,
    end_at: datetime = END,
) -> DatasetDefinition:
    return DatasetDefinition(
        sources
        or (
            DatasetSourceDefinition(A, "source-a"),
            DatasetSourceDefinition(B, "source-b"),
        ),
        start_at,
        end_at,
    )


def _execution(
    instrument: InstrumentId,
    *,
    quantity: int = 10,
    tick: str = "0.05",
) -> InstrumentExecutionDefinition:
    return InstrumentExecutionDefinition(
        instrument_id=instrument,
        quantity=Quantity(quantity),
        tick_schedule=TickSizeSchedule(
            instrument_id=instrument,
            rules=(
                TickSizeRule(
                    tick_size=Price(Decimal(tick)),
                    effective_from=date(2026, 1, 1),
                ),
            ),
        ),
    )


def _selection(
    strategy_id: str = "intraday_momentum_v1",
    strategy_version: str = "1.0.0",
) -> StrategySelection:
    return StrategySelection(strategy_id, strategy_version, {})


def _experiment(
    *,
    universe: UniverseDefinition | None = None,
    dataset: DatasetDefinition | None = None,
    execution: tuple[InstrumentExecutionDefinition, ...] | None = None,
    calculation_version: str = "engine-v1",
    selection: StrategySelection | None = None,
) -> ExperimentDefinition:
    return ExperimentDefinition.create(
        strategy_selection=selection or _selection(),
        universe=universe or _universe(A, B),
        dataset=dataset or _dataset(),
        engine_calculation_version=calculation_version,
        execution=execution or (_execution(A), _execution(B)),
    )


def test_universe_identity_is_canonical_and_order_independent() -> None:
    first = _universe(B, A)
    second = _universe(A, B)

    assert first.instruments == (A, B)
    assert first == second
    assert first.universe_id == second.universe_id


def test_universe_rejects_empty_or_duplicate_instruments() -> None:
    with pytest.raises(ValueError, match="at least one"):
        UniverseDefinition(())
    with pytest.raises(ValueError, match="unique"):
        _universe(A, A)


def test_dataset_identity_is_content_and_range_derived() -> None:
    first = _dataset(
        (
            DatasetSourceDefinition(B, "source-b"),
            DatasetSourceDefinition(A, "source-a"),
        )
    )
    same = _dataset()
    changed_source = _dataset(
        (
            DatasetSourceDefinition(A, "source-a-v2"),
            DatasetSourceDefinition(B, "source-b"),
        )
    )
    changed_range = _dataset(end_at=datetime(2026, 2, 1, 15, 30, tzinfo=IST))

    assert first.sources == same.sources
    assert first.dataset_id == same.dataset_id
    assert changed_source.dataset_id != same.dataset_id
    assert changed_range.dataset_id != same.dataset_id


def test_dataset_rejects_invalid_range_and_duplicate_instrument() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _dataset(start_at=datetime(2026, 1, 1, 9, 15))
    with pytest.raises(ValueError, match="after start_at"):
        _dataset(start_at=END, end_at=START)
    with pytest.raises(ValueError, match="one source per instrument"):
        _dataset(
            (
                DatasetSourceDefinition(A, "source-a"),
                DatasetSourceDefinition(A, "source-a-2"),
            )
        )


def test_experiment_resolves_registered_strategy_and_canonicalizes_execution() -> None:
    experiment = _experiment(execution=(_execution(B), _execution(A)))

    assert experiment.strategy_identity.strategy_id == "intraday_momentum_v1"
    assert experiment.strategy_identity.strategy_version == "1.0.0"
    assert experiment.config_identity.config_hash == (
        "fd6ec6027dcd2d661d60c3ccfa4e7de3873b2400c8ad2e0ca1323f358b967956"
    )
    assert tuple(item.instrument_id for item in experiment.execution) == (A, B)


def test_equivalent_semantic_experiments_have_identical_identity() -> None:
    first = _experiment(
        universe=_universe(B, A),
        dataset=_dataset(
            (
                DatasetSourceDefinition(B, "source-b"),
                DatasetSourceDefinition(A, "source-a"),
            )
        ),
        execution=(_execution(B), _execution(A)),
    )
    second = _experiment()

    assert first.experiment_id == second.experiment_id


@pytest.mark.parametrize(
    "changed",
    (
        _experiment(
            dataset=_dataset(
                (
                    DatasetSourceDefinition(A, "source-a-v2"),
                    DatasetSourceDefinition(B, "source-b"),
                )
            )
        ),
        _experiment(calculation_version="engine-v2"),
        _experiment(execution=(_execution(A, quantity=11), _execution(B))),
        _experiment(execution=(_execution(A, tick="0.10"), _execution(B))),
        _experiment(selection=_selection("rsi_mean_reversion_v1")),
    ),
)
def test_material_experiment_changes_change_identity(changed: ExperimentDefinition) -> None:
    assert changed.experiment_id != _experiment().experiment_id


def test_experiment_requires_exact_universe_dataset_execution_coverage() -> None:
    with pytest.raises(ValueError, match="dataset instruments"):
        _experiment(
            dataset=DatasetDefinition(
                (DatasetSourceDefinition(A, "source-a"),),
                START,
                END,
            )
        )

    with pytest.raises(ValueError, match="execution instruments"):
        _experiment(execution=(_execution(A),))


def test_experiment_rejects_duplicate_execution_and_blank_calculation_version() -> None:
    with pytest.raises(ValueError, match="unique"):
        _experiment(execution=(_execution(A), _execution(A), _execution(B)))
    with pytest.raises(ValueError, match="must not be empty"):
        _experiment(calculation_version=" ")


def test_experiment_fails_before_research_run_for_unknown_strategy() -> None:
    with pytest.raises(UnknownStrategyError, match="Unknown strategy"):
        _experiment(selection=_selection("not_registered"))
