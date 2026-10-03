"""Strategy-neutral indicator checkpoint reconciliation for restart recovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Never

from signalforge.domain.indicators import IndicatorSnapshot
from signalforge.domain.market import CompletedCandle
from signalforge.runtime.indicators import (
    IndicatorContinuity,
    IndicatorContinuityBroken,
    IndicatorEngine,
    IndicatorEngineState,
)


class IndicatorRecoveryError(RuntimeError):
    """Raised when persisted indicator continuity cannot be recovered safely."""


@dataclass(frozen=True, slots=True)
class RecoveryCandle:
    """One authoritative post-checkpoint candle plus upstream continuity evidence.

    ``continuity_ok`` is supplied by the canonical input/session boundary. The
    reconciler deliberately does not infer NSE session calendars or broker/feed
    gaps inside the numerical indicator layer.
    """

    candle: CompletedCandle
    continuity_ok: bool


class IndicatorRecoveryReconciler:
    """Restore a checkpoint and apply strictly post-checkpoint candles exactly once."""

    def __init__(self, checkpoint: IndicatorEngineState) -> None:
        if checkpoint.continuity is IndicatorContinuity.BROKEN:
            raise IndicatorRecoveryError("persisted indicator checkpoint continuity is broken")
        self._engine = IndicatorEngine(
            checkpoint.instrument_id,
            checkpoint.calculation_version,
            requirements=checkpoint.requirements,
            state=checkpoint,
        )
        if self._engine.state != checkpoint:
            raise IndicatorRecoveryError("indicator checkpoint did not restore exactly")

    @property
    def engine(self) -> IndicatorEngine:
        """Return the restored/reconciled indicator engine."""

        return self._engine

    @property
    def state(self) -> IndicatorEngineState:
        """Return current lossless indicator state."""

        return self._engine.state

    def reconcile(self, inputs: Iterable[RecoveryCandle]) -> tuple[IndicatorSnapshot, ...]:
        """Apply authoritative candles strictly after the current checkpoint boundary.

        The caller owns canonical source/session continuity. Every input therefore
        carries an explicit continuity assertion. A false assertion, stale/overlapping
        interval, wrong instrument, or invalid candle fails recovery and leaves the
        in-memory indicator engine BROKEN.
        """

        snapshots: list[IndicatorSnapshot] = []
        for item in inputs:
            candle = item.candle
            boundary = self._engine.state.last_interval

            if candle.instrument_id != self._engine.instrument_id:
                self._fail("recovery candle instrument contradicts indicator checkpoint")

            if boundary is not None and candle.interval.start < boundary.end:
                self._fail(
                    "recovery candles must be strictly after the indicator checkpoint boundary"
                )

            if not item.continuity_ok:
                self._fail("authoritative recovery source cannot prove candle continuity")

            try:
                snapshots.append(self._engine.update(candle, continuity_ok=True))
            except IndicatorContinuityBroken as exc:
                raise IndicatorRecoveryError(str(exc)) from exc
            except ValueError as exc:
                self._engine.break_continuity()
                raise IndicatorRecoveryError(str(exc)) from exc

        return tuple(snapshots)

    def _fail(self, message: str) -> Never:
        self._engine.break_continuity()
        raise IndicatorRecoveryError(message)
