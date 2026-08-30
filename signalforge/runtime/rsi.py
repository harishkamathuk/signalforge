"""Canonical incremental RSI(14) calculation for Strategy V1."""

from dataclasses import dataclass
from decimal import Decimal

_PERIOD = 14
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_FIFTY = Decimal("50")


@dataclass(frozen=True, slots=True)
class RsiState:
    """Serializable numerical state required for exact RSI continuation."""

    samples: int
    previous_close: Decimal | None
    seed_gain_sum: Decimal
    seed_loss_sum: Decimal
    average_gain: Decimal | None
    average_loss: Decimal | None

    def __post_init__(self) -> None:
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError("RSI samples must be an integer")
        if self.samples < 0:
            raise ValueError("RSI samples must not be negative")
        _require_optional_finite_decimal(self.previous_close, name="previous_close")
        _require_finite_decimal(self.seed_gain_sum, name="seed_gain_sum")
        _require_finite_decimal(self.seed_loss_sum, name="seed_loss_sum")
        _require_optional_finite_decimal(self.average_gain, name="average_gain")
        _require_optional_finite_decimal(self.average_loss, name="average_loss")
        if self.seed_gain_sum < 0 or self.seed_loss_sum < 0:
            raise ValueError("RSI seed gain/loss sums must not be negative")
        if self.average_gain is not None and self.average_gain < 0:
            raise ValueError("RSI average_gain must not be negative")
        if self.average_loss is not None and self.average_loss < 0:
            raise ValueError("RSI average_loss must not be negative")
        self._validate_phase()

    def _validate_phase(self) -> None:
        changes = max(self.samples - 1, 0)
        if self.samples == 0:
            if self.previous_close is not None:
                raise ValueError("Empty RSI state cannot have previous_close")
        elif self.previous_close is None:
            raise ValueError("Non-empty RSI state requires previous_close")

        if changes < _PERIOD:
            if self.average_gain is not None or self.average_loss is not None:
                raise ValueError("Unready RSI state cannot have Wilder averages")
        else:
            if self.average_gain is None or self.average_loss is None:
                raise ValueError("Ready RSI state requires Wilder averages")
            if self.seed_gain_sum != 0 or self.seed_loss_sum != 0:
                raise ValueError("Ready RSI state must not retain seed sums")


class Rsi14:
    """Incremental Wilder RSI(14) using the frozen Strategy V1 convention."""

    def __init__(self, *, state: RsiState | None = None) -> None:
        state = state or RsiState(
            samples=0,
            previous_close=None,
            seed_gain_sum=_ZERO,
            seed_loss_sum=_ZERO,
            average_gain=None,
            average_loss=None,
        )
        self._samples = state.samples
        self._previous_close = state.previous_close
        self._seed_gain_sum = state.seed_gain_sum
        self._seed_loss_sum = state.seed_loss_sum
        self._average_gain = state.average_gain
        self._average_loss = state.average_loss

    @property
    def samples(self) -> int:
        return self._samples

    @property
    def ready(self) -> bool:
        return self._average_gain is not None

    @property
    def value(self) -> Decimal | None:
        if self._average_gain is None or self._average_loss is None:
            return None
        return _rsi_value(self._average_gain, self._average_loss)

    def snapshot(self) -> RsiState:
        return RsiState(
            samples=self._samples,
            previous_close=self._previous_close,
            seed_gain_sum=self._seed_gain_sum,
            seed_loss_sum=self._seed_loss_sum,
            average_gain=self._average_gain,
            average_loss=self._average_loss,
        )

    def update(self, close: Decimal) -> Decimal | None:
        """Consume one completed-candle close and return RSI when ready."""

        _require_finite_decimal(close, name="close")

        if self._previous_close is None:
            self._previous_close = close
            self._samples = 1
            return None

        delta = close - self._previous_close
        gain = max(delta, _ZERO)
        loss = max(-delta, _ZERO)

        if self._average_gain is None:
            self._seed_gain_sum += gain
            self._seed_loss_sum += loss
            self._samples += 1
            self._previous_close = close
            if self._samples == _PERIOD + 1:
                divisor = Decimal(_PERIOD)
                self._average_gain = self._seed_gain_sum / divisor
                self._average_loss = self._seed_loss_sum / divisor
                self._seed_gain_sum = _ZERO
                self._seed_loss_sum = _ZERO
            return self.value

        assert self._average_loss is not None
        period = Decimal(_PERIOD)
        self._average_gain = ((self._average_gain * Decimal(_PERIOD - 1)) + gain) / period
        self._average_loss = ((self._average_loss * Decimal(_PERIOD - 1)) + loss) / period
        self._samples += 1
        self._previous_close = close
        return self.value


def _rsi_value(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_gain == 0 and average_loss == 0:
        return _FIFTY
    if average_loss == 0:
        return _HUNDRED
    if average_gain == 0:
        return _ZERO
    relative_strength = average_gain / average_loss
    return _HUNDRED - (_HUNDRED / (Decimal(1) + relative_strength))


def _require_finite_decimal(value: Decimal, *, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"RSI {name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"RSI {name} must be finite")


def _require_optional_finite_decimal(value: Decimal | None, *, name: str) -> None:
    if value is not None:
        _require_finite_decimal(value, name=name)
