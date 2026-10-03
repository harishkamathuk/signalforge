"""Strategy-neutral lifecycle hydration after successful indicator recovery."""

from __future__ import annotations

from dataclasses import dataclass

from signalforge.domain.armed import ArmedSetupState
from signalforge.domain.positions import PositionState
from signalforge.domain.trades import TradeState
from signalforge.runtime.indicator_recovery import IndicatorRecoveryResult
from signalforge.runtime.indicators import IndicatorContinuity
from signalforge.runtime.lifecycle import LifecycleCoordinator, LifecycleSnapshot
from signalforge.runtime.recovery import RecoveredLifecycle


class LifecycleRecoveryError(RuntimeError):
    """Raised when persisted lifecycle state cannot be hydrated safely."""


@dataclass(frozen=True, slots=True)
class LifecycleRecoveryResult:
    """Operational lifecycle released only after successful prerequisite recovery."""

    coordinator: LifecycleCoordinator
    snapshot: LifecycleSnapshot


class LifecycleRecoveryHydrator:
    """Install authoritative persisted lifecycle facts without replaying history."""

    def hydrate(
        self,
        *,
        indicator_result: IndicatorRecoveryResult,
        recovered: RecoveredLifecycle,
        coordinator: LifecycleCoordinator,
    ) -> LifecycleRecoveryResult:
        """Hydrate ARMED or OPEN state only after indicator reconciliation succeeded."""

        strategy_identity = coordinator.strategy.identity
        config_identity = coordinator.strategy.config_identity
        if (
            strategy_identity != coordinator.run.strategy
            or config_identity.config_id != coordinator.run.config_id
            or config_identity.config_hash != coordinator.run.config_hash
        ):
            raise LifecycleRecoveryError(
                "configured strategy identity contradicts recovered lifecycle run"
            )

        indicator_state = indicator_result.engine.state
        if indicator_state.continuity is not IndicatorContinuity.HEALTHY:
            raise LifecycleRecoveryError("indicator recovery is not healthy")
        if indicator_state.instrument_id != coordinator.signal_lifecycle.tick_schedule.instrument_id:
            raise LifecycleRecoveryError(
                "indicator recovery instrument contradicts lifecycle runtime"
            )

        setup = recovered.setup
        signal = recovered.signal
        trade = recovered.trade
        position = recovered.position

        if setup is not None and setup.state is ArmedSetupState.ARMED:
            if signal is None:
                raise LifecycleRecoveryError("ARMED recovery requires persisted Signal")
            snapshot = coordinator.hydrate_armed(
                signal=signal,
                setup=setup,
                transitions=recovered.transitions,
            )
            return LifecycleRecoveryResult(coordinator, snapshot)

        if trade is not None and trade.state is TradeState.OPEN:
            if (
                signal is None
                or setup is None
                or recovered.trigger is None
                or recovered.intent is None
                or recovered.fill is None
                or position is None
                or position.state is not PositionState.OPEN
            ):
                raise LifecycleRecoveryError("OPEN recovery graph is incomplete")
            snapshot = coordinator.hydrate_open(
                signal=signal,
                setup=setup,
                trigger=recovered.trigger,
                intent=recovered.intent,
                fill=recovered.fill,
                trade=trade,
                position=position,
                transitions=recovered.transitions,
            )
            return LifecycleRecoveryResult(coordinator, snapshot)

        # Terminal or inactive historical state is intentionally not replayed into an
        # actionable lifecycle. Recovery must not convert EXPIRED/CLOSED/rejected facts
        # back into ARMED or OPEN state.
        return LifecycleRecoveryResult(coordinator, coordinator.snapshot())
