from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import signalforge.research.historical_bars as historical_bars_module
from signalforge.config.identity import ConfigIdentity, ConfigStatus, identify_config
from signalforge.config.strategy_registry import (
    StrategyRegistration,
    StrategyRegistry,
    StrategySelection,
)
from signalforge.domain.execution import Fill
from signalforge.domain.ids import InstrumentId
from signalforge.domain.indicators import EmaRequirement, IndicatorRequirements
from signalforge.domain.market import CandleQuality, CompletedCandle, MarketEvent
from signalforge.domain.money import Price
from signalforge.domain.provenance import StrategyIdentity
from signalforge.domain.signals import Signal
from signalforge.domain.time import IST, CandleInterval, to_utc
from signalforge.research.historical_bars import (
    CorporateActionPolicy,
    HistoricalBar,
    HistoricalBarDataset,
    HistoricalBarResearchRunner,
    HistoricalContinuityError,
    HistoricalDatasetManifest,
    aggregate_one_minute_to_five_minute,
    load_historical_bar_fixture,
)
from signalforge.runtime.strategy import (
    ArmedEventDecision,
    ArmedSetupView,
    ArmIntent,
    CompletedCandleStrategyContext,
    PositionEconomics,
    StrategyDecision,
)

INSTRUMENT = InstrumentId("NSE:TEST")
VERSION = "historical-bar-v1"
SESSION_DATE = date(2026, 10, 9)


def _bar(
    minute: int,
    *,
    close: str | None = None,
    start_hour: int = 9,
    session_date: date = SESSION_DATE,
) -> HistoricalBar:
    start = datetime.combine(session_date, datetime.min.time(), tzinfo=IST).replace(
        hour=start_hour,
        minute=minute,
    )
    base = Decimal(str(100 + minute))
    close_value = base + Decimal("1") if close is None else Decimal(close)
    return HistoricalBar(
        instrument_id=INSTRUMENT,
        interval=CandleInterval(start=start, end=start + timedelta(minutes=1)),
        open=Price(base),
        high=Price(max(base + Decimal("2"), close_value)),
        low=Price(min(base - Decimal("1"), close_value)),
        close=Price(close_value),
        volume=1000 + minute,
        quality=CandleQuality.VALID,
        source_provider="fixture",
        source_record_count=1,
        provider_timestamp_raw=start.isoformat(),
        provider_timestamp_interpreted=start,
        canonicalisation_version=VERSION,
    )


def _bars(start_minute: int, count: int) -> tuple[HistoricalBar, ...]:
    return tuple(_bar(start_minute + offset) for offset in range(count))


def _manifest(
    bars: tuple[HistoricalBar, ...],
    *,
    duplicates: int = 0,
    acquired_at: datetime | None = None,
    canonical_row_count: int | None = None,
    expected_session_dates: tuple[date, ...] = (SESSION_DATE,),
    corrupt_rejected_count: int = 0,
) -> HistoricalDatasetManifest:
    first = min(bar.interval.start for bar in bars)
    last = max(bar.interval.end for bar in bars)
    canonical_count = (
        len(bars) - duplicates if canonical_row_count is None else canonical_row_count
    )
    return HistoricalDatasetManifest(
        provider="fixture",
        acquisition_adapter="test-fixture",
        acquisition_version="1",
        requested_instrument="NSE:TEST",
        resolved_provider_instrument="NSE:TEST",
        instrument_id=INSTRUMENT,
        requested_start=datetime.combine(
            expected_session_dates[0],
            datetime.min.time(),
            tzinfo=IST,
        ).replace(hour=9, minute=15),
        requested_end=datetime.combine(
            expected_session_dates[-1],
            datetime.min.time(),
            tzinfo=IST,
        ).replace(hour=15, minute=30),
        returned_start=first,
        returned_end=last,
        interval_minutes=1,
        acquired_at=acquired_at or datetime(2026, 10, 11, 12, 0, tzinfo=IST),
        provider_timestamp_representation="ISO-8601",
        timezone_interpretation="Asia/Kolkata interval-start",
        canonicalisation_version=VERSION,
        expected_session_dates=expected_session_dates,
        raw_row_count=len(bars) + corrupt_rejected_count,
        canonical_row_count=canonical_count,
        missing_interval_count=len(expected_session_dates) * 375 - canonical_count,
        duplicate_observation_count=duplicates,
        corrupt_rejected_count=corrupt_rejected_count,
        corporate_action_policy=CorporateActionPolicy.UNKNOWN,
        limitations=("test fixture",),
    )


def _dataset(bars: tuple[HistoricalBar, ...]) -> HistoricalBarDataset:
    return HistoricalBarDataset(manifest=_manifest(bars), bars=bars)


@dataclass(frozen=True, slots=True)
class _CloseAboveEmaDecision:
    instrument_id: InstrumentId
    interval: CandleInterval
    qualified: bool
    actionable: bool
    reasons: tuple[str, ...]


class _CloseAboveEmaTestStrategy:
    """Test-only third strategy shape for shared-boundary pressure."""

    _identity = StrategyIdentity("test_close_above_ema", "1.0.0")
    _config_identity = identify_config(
        {"strategy": "test_close_above_ema", "ema_period": 3},
        status=ConfigStatus.EXPERIMENTAL,
    )
    _requirements = IndicatorRequirements.of(EmaRequirement(3))

    @property
    def identity(self) -> StrategyIdentity:
        return self._identity

    @property
    def config_identity(self) -> ConfigIdentity:
        return self._config_identity

    @property
    def indicator_requirements(self) -> IndicatorRequirements:
        return self._requirements

    def evaluate_completed_candle(
        self,
        context: CompletedCandleStrategyContext,
    ) -> _CloseAboveEmaDecision:
        ema = context.indicators.ema(3)
        close = context.candle.close
        actionable = ema is not None and close is not None and close.value > ema
        return _CloseAboveEmaDecision(
            instrument_id=context.candle.instrument_id,
            interval=context.candle.interval,
            qualified=actionable,
            actionable=actionable,
            reasons=("close_above_ema3",) if actionable else ("not_ready_or_not_above",),
        )

    def arm_intent(
        self,
        candle: CompletedCandle,
        decision: StrategyDecision,
    ) -> ArmIntent:
        raise AssertionError("historical-bar signal audit must not invoke lifecycle policy")

    def evaluate_armed_market_event(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        event: MarketEvent,
    ) -> ArmedEventDecision:
        raise AssertionError("historical-bar signal audit must not invoke lifecycle policy")

    def evaluate_armed_completed_candle(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        candle: CompletedCandle,
    ) -> ArmedEventDecision:
        raise AssertionError("historical-bar signal audit must not invoke lifecycle policy")

    def evaluate_armed_time(
        self,
        signal: Signal,
        setup: ArmedSetupView,
        at: datetime,
    ) -> ArmedEventDecision:
        raise AssertionError("historical-bar signal audit must not invoke lifecycle policy")

    def post_fill_economics(
        self,
        fill: Fill,
        setup: ArmedSetupView,
    ) -> PositionEconomics:
        raise AssertionError("historical-bar signal audit must not invoke lifecycle policy")


def _build_close_above_ema_test_strategy(
    parameters: Mapping[str, object],
) -> _CloseAboveEmaTestStrategy:
    del parameters
    return _CloseAboveEmaTestStrategy()


def test_historical_bar_runner_has_no_real_strategy_dispatch() -> None:
    source = inspect.getsource(historical_bars_module)
    forbidden = (
        "intraday_momentum_v1",
        "rsi_mean_reversion_v1",
        "IntradayMomentumV1Strategy",
        "RsiMeanReversionV1Strategy",
    )
    for token in forbidden:
        assert token not in source


def test_historical_bar_runner_supports_both_registered_strategies() -> None:
    root = Path(__file__).parents[3]
    dataset = load_historical_bar_fixture(
        root / "examples/research/historical-bars-one-session.json"
    )
    runner = HistoricalBarResearchRunner()

    momentum = runner.run(
        dataset,
        strategy_selection=StrategySelection("intraday_momentum_v1", "1.0.0", {}),
        engine_calculation_version="engine-v1",
    )
    mean_reversion = runner.run(
        dataset,
        strategy_selection=StrategySelection("rsi_mean_reversion_v1", "1.0.0", {}),
        engine_calculation_version="engine-v1",
    )

    assert momentum.strategy_id == "intraday_momentum_v1"
    assert mean_reversion.strategy_id == "rsi_mean_reversion_v1"
    assert momentum.config_hash != mean_reversion.config_hash
    assert len(momentum.decisions) == 75
    assert len(mean_reversion.decisions) == 75
    assert any(item.indicator_ready for item in momentum.decisions)
    assert any(item.indicator_ready for item in mean_reversion.decisions)


def test_historical_bar_runner_supports_third_test_only_strategy_shape() -> None:
    root = Path(__file__).parents[3]
    dataset = load_historical_bar_fixture(
        root / "examples/research/historical-bars-one-session.json"
    )
    registry = StrategyRegistry(
        (
            StrategyRegistration(
                "test_close_above_ema",
                "1.0.0",
                _build_close_above_ema_test_strategy,
            ),
        )
    )
    result = HistoricalBarResearchRunner(registry=registry).run(
        dataset,
        strategy_selection=StrategySelection("test_close_above_ema", "1.0.0", {}),
        engine_calculation_version="engine-v1",
    )

    assert result.strategy_id == "test_close_above_ema"
    assert len(result.decisions) == 75
    assert result.decisions[0].indicator_ready is False
    assert any(item.indicator_ready for item in result.decisions)
    assert any(item.actionable for item in result.decisions)


def test_historical_bar_requires_exact_valid_one_minute_observation() -> None:
    bar = _bar(15)
    assert bar.interval.start == to_utc(datetime(2026, 10, 9, 9, 15, tzinfo=IST))
    assert bar.provider_timestamp_interpreted == bar.interval.start

    with pytest.raises(ValueError, match="exactly one minute"):
        replace(
            bar,
            interval=CandleInterval(
                start=datetime(2026, 10, 9, 9, 15, tzinfo=IST),
                end=datetime(2026, 10, 9, 9, 17, tzinfo=IST),
            ),
        )
    with pytest.raises(ValueError, match="quality must be VALID"):
        replace(bar, quality=CandleQuality.INCOMPLETE)
    with pytest.raises(ValueError, match="volume must not be negative"):
        replace(bar, volume=-1)
    with pytest.raises(ValueError, match="prices must be strictly positive"):
        replace(bar, open=Price(Decimal("0")))


def test_manifest_requires_complete_declared_session_range() -> None:
    bar = _bar(15)
    manifest = _manifest((bar,))

    with pytest.raises(ValueError, match="complete declared regular NSE sessions"):
        replace(
            manifest,
            requested_start=datetime(2026, 10, 9, 9, 16, tzinfo=IST),
        )
    with pytest.raises(ValueError, match="complete declared regular NSE sessions"):
        replace(
            manifest,
            requested_end=datetime(2026, 10, 9, 15, 29, tzinfo=IST),
        )


def test_dataset_deduplicates_exact_observation_and_rejects_contradiction() -> None:
    bar = _bar(15)
    duplicate_dataset = HistoricalBarDataset(
        manifest=_manifest((bar, bar), duplicates=1, canonical_row_count=1),
        bars=(bar, bar),
    )
    assert duplicate_dataset.bars == (bar,)

    contradictory = replace(bar, close=Price(bar.close.value + Decimal("1")))
    with pytest.raises(ValueError, match="Contradictory duplicate"):
        HistoricalBarDataset(
            manifest=_manifest((bar, contradictory), duplicates=1, canonical_row_count=1),
            bars=(bar, contradictory),
        )


def test_dataset_rejects_noncanonical_input_order() -> None:
    bars = (_bar(16), _bar(15))
    with pytest.raises(ValueError, match="strict canonical chronological order"):
        HistoricalBarDataset(manifest=_manifest(bars), bars=bars)


def test_dataset_rejects_bar_from_undeclared_session() -> None:
    declared_bar = _bar(15)
    undeclared_bar = _bar(15, session_date=date(2026, 10, 8))
    manifest = _manifest((declared_bar,))

    with pytest.raises(ValueError, match="session date is not declared"):
        HistoricalBarDataset(manifest=manifest, bars=(undeclared_bar,))


def test_manifest_identity_counts_must_match_canonical_content() -> None:
    bars = _bars(15, 5)
    manifest = _manifest(bars)

    with pytest.raises(ValueError, match="raw row count contradicts"):
        HistoricalBarDataset(
            manifest=replace(manifest, raw_row_count=manifest.raw_row_count + 1),
            bars=bars,
        )
    with pytest.raises(ValueError, match="missing interval count contradicts"):
        HistoricalBarDataset(
            manifest=replace(
                manifest,
                missing_interval_count=manifest.missing_interval_count + 1,
            ),
            bars=bars,
        )


def test_complete_five_minute_bucket_has_exact_ohlcv() -> None:
    bars = _bars(15, 5)
    candles = aggregate_one_minute_to_five_minute(_dataset(bars))
    first = candles[0]

    assert len(candles) == 75
    assert first.quality is CandleQuality.VALID
    assert first.open == bars[0].open
    assert first.close == bars[-1].close
    assert first.high == Price(max(item.high.value for item in bars))
    assert first.low == Price(min(item.low.value for item in bars))
    assert first.volume == sum(item.volume for item in bars)


def test_missing_minute_is_incomplete_and_empty_bucket_is_missing() -> None:
    bars = _bars(15, 4)
    candles = aggregate_one_minute_to_five_minute(_dataset(bars))

    assert candles[0].quality is CandleQuality.INCOMPLETE
    assert candles[0].open is not None
    assert candles[1].quality is CandleQuality.MISSING
    assert candles[1].open is None
    assert candles[1].high is None
    assert candles[1].low is None
    assert candles[1].close is None
    assert candles[1].volume is None


def test_entire_declared_session_with_no_rows_is_explicitly_missing() -> None:
    prior_session = date(2026, 10, 8)
    bars = _bars(15, 5)
    dataset = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            expected_session_dates=(prior_session, SESSION_DATE),
        ),
        bars=bars,
    )

    candles = aggregate_one_minute_to_five_minute(dataset)

    assert len(candles) == 150
    assert all(
        candle.quality is CandleQuality.MISSING
        for candle in candles[:75]
    )
    assert candles[75].quality is CandleQuality.VALID


def test_dataset_identity_ignores_operational_provenance_but_changes_with_content() -> None:
    bars = _bars(15, 5)
    first = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            acquired_at=datetime(2026, 10, 11, 12, 0, tzinfo=IST),
        ),
        bars=bars,
    )
    second = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            acquired_at=datetime(2026, 10, 12, 17, 0, tzinfo=IST),
        ),
        bars=bars,
    )
    assert first.dataset_id == second.dataset_id

    operationally_different = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            corrupt_rejected_count=1,
        ),
        bars=bars,
    )
    assert operationally_different.dataset_id == first.dataset_id

    changed_bars = (*bars[:-1], replace(bars[-1], volume=bars[-1].volume + 1))
    changed = HistoricalBarDataset(
        manifest=_manifest(changed_bars),
        bars=changed_bars,
    )
    assert changed.dataset_id != first.dataset_id


def test_fixture_loads_and_runs_existing_strategy_indicator_path_deterministically() -> None:
    root = Path(__file__).parents[3]
    dataset = load_historical_bar_fixture(
        root / "examples/research/historical-bars-one-session.json"
    )
    runner = HistoricalBarResearchRunner()
    selection = StrategySelection("intraday_momentum_v1", "1.0.0", {})

    first = runner.run(
        dataset,
        strategy_selection=selection,
        engine_calculation_version="engine-v1",
    )
    second = runner.run(
        dataset,
        strategy_selection=selection,
        engine_calculation_version="engine-v1",
    )

    assert first == second
    assert first.semantic_mapping() == second.semantic_mapping()
    assert first.derived_candles == 75
    assert first.valid_candles == 75
    assert first.missing_candles == 0
    assert first.incomplete_candles == 0
    assert len(first.decisions) == 75
    assert any(item.indicator_ready for item in first.decisions)


def test_non_valid_bucket_fails_research_explicitly() -> None:
    bars = _bars(15, 4)
    dataset = _dataset(bars)

    with pytest.raises(HistoricalContinuityError) as exc_info:
        HistoricalBarResearchRunner().run(
            dataset,
            strategy_selection=StrategySelection(
                "intraday_momentum_v1",
                "1.0.0",
                {},
            ),
            engine_calculation_version="engine-v1",
        )

    assert exc_info.value.candle.quality is CandleQuality.INCOMPLETE
    assert exc_info.value.candle.interval.start == to_utc(
        datetime(2026, 10, 9, 9, 15, tzinfo=IST)
    )


def test_fully_missing_declared_session_fails_research_explicitly() -> None:
    prior_session = date(2026, 10, 8)
    bars = _bars(15, 5)
    dataset = HistoricalBarDataset(
        manifest=_manifest(
            bars,
            expected_session_dates=(prior_session, SESSION_DATE),
        ),
        bars=bars,
    )

    with pytest.raises(HistoricalContinuityError) as exc_info:
        HistoricalBarResearchRunner().run(
            dataset,
            strategy_selection=StrategySelection(
                "intraday_momentum_v1",
                "1.0.0",
                {},
            ),
            engine_calculation_version="engine-v1",
        )

    assert exc_info.value.candle.quality is CandleQuality.MISSING
    assert exc_info.value.candle.interval.start == to_utc(
        datetime(2026, 10, 8, 9, 15, tzinfo=IST)
    )
