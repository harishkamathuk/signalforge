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


@dataclass(frozen=True, slots=True)
class IndicatorRecoveryResult:
    """Successfully reconciled engine plus diagnostic catch-up snapshots."""

    engine: IndicatorEngine
    snapshots: tuple[IndicatorSnapshot, ...]


class IndicatorRecoveryReconciler:
    """Restore a checkpoint and apply strictly post-checkpoint candles exactly once.

    A usable ``IndicatorEngine`` is released only in ``IndicatorRecoveryResult``
    after the full reconciliation input has succeeded. This prevents callers from
    resuming strategy evaluation against partially reconciled indicator state.
    """

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
        self._terminal = False

    @property
    def state(self) -> IndicatorEngineState:
        """Return current state for recovery diagnostics and failure inspection."""

        return self._engine.state

    def reconcile(self, inputs: Iterable[RecoveryCandle]) -> IndicatorRecoveryResult:
        """Apply authoritative candles strictly after the current checkpoint boundary.

        The caller owns canonical source/session continuity. Every input therefore
        carries an explicit continuity assertion. A false assertion, stale/overlapping
        interval, wrong instrument, or invalid candle fails recovery and leaves the
        in-memory indicator engine BROKEN.

        The reconciler is one-shot. After success or failure, construct a fresh
        reconciler from the authoritative persisted checkpoint for any retry.
        """

        if self._terminal:
            raise IndicatorRecoveryError("indicator recovery reconciliation is already terminal")

        snapshots: list[IndicatorSnapshot] = []
        try:
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

                snapshots.append(self._engine.update(candle, continuity_ok=True))
        except IndicatorRecoveryError:
            raise
        except IndicatorContinuityBroken as exc:
            self._terminal = True
            raise IndicatorRecoveryError(str(exc)) from exc
        except ValueError as exc:
            self._engine.break_continuity()
            self._terminal = True
            raise IndicatorRecoveryError(str(exc)) from exc

        self._terminal = True
        return IndicatorRecoveryResult(self._engine, tuple(snapshots))

    def _fail(self, message: str) -> Never:
        self._engine.break_continuity()
        self._terminal = True
        raise IndicatorRecoveryError(message)
