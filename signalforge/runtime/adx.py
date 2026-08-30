"""Canonical incremental ADX(14) calculation for Strategy V1."""

from dataclasses import dataclass
from decimal import Decimal

_PERIOD = 14
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class AdxValues:
    tr: Decimal | None
    plus_dm: Decimal | None
    minus_dm: Decimal | None
    plus_di: Decimal | None
    minus_di: Decimal | None
    dx: Decimal | None
    adx: Decimal | None


@dataclass(frozen=True, slots=True)
class AdxState:
    samples: int
    previous_high: Decimal | None
    previous_low: Decimal | None
    previous_close: Decimal | None
    seed_tr_sum: Decimal
    seed_plus_dm_sum: Decimal
    seed_minus_dm_sum: Decimal
    smoothed_tr: Decimal | None
    smoothed_plus_dm: Decimal | None
    smoothed_minus_dm: Decimal | None
    dx_seed_sum: Decimal
    dx_seed_count: int
    adx: Decimal | None

    def __post_init__(self) -> None:
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError("ADX samples must be an integer")
        if self.samples < 0:
            raise ValueError("ADX samples must not be negative")
        if isinstance(self.dx_seed_count, bool) or not isinstance(self.dx_seed_count, int):
            raise TypeError("ADX dx_seed_count must be an integer")
        if not 0 <= self.dx_seed_count <= _PERIOD:
            raise ValueError("ADX dx_seed_count must be between 0 and 14")

        for name, value in (
            ("previous_high", self.previous_high),
            ("previous_low", self.previous_low),
            ("previous_close", self.previous_close),
            ("smoothed_tr", self.smoothed_tr),
            ("smoothed_plus_dm", self.smoothed_plus_dm),
            ("smoothed_minus_dm", self.smoothed_minus_dm),
            ("adx", self.adx),
        ):
            _require_optional_decimal(value, name=name)
        for name, value in (
            ("seed_tr_sum", self.seed_tr_sum),
            ("seed_plus_dm_sum", self.seed_plus_dm_sum),
            ("seed_minus_dm_sum", self.seed_minus_dm_sum),
            ("dx_seed_sum", self.dx_seed_sum),
        ):
            _require_decimal(value, name=name)
            if value < 0:
                raise ValueError(f"ADX {name} must not be negative")

        previous = (self.previous_high, self.previous_low, self.previous_close)
        if self.samples == 0:
            if any(value is not None for value in previous):
                raise ValueError("Empty ADX state cannot retain previous candle values")
        elif any(value is None for value in previous):
            raise ValueError("Non-empty ADX state requires previous candle values")

        smoothed = (self.smoothed_tr, self.smoothed_plus_dm, self.smoothed_minus_dm)
        if self.samples < _PERIOD + 1:
            if any(value is not None for value in smoothed):
                raise ValueError("ADX smoothing cannot exist before C14")
            if self.dx_seed_count != 0 or self.dx_seed_sum != 0 or self.adx is not None:
                raise ValueError("ADX/DX seed state cannot exist before C14")
        else:
            if any(value is None for value in smoothed):
                raise ValueError("ADX smoothing is required from C14 onward")
            if self.samples < 28 and self.adx is not None:
                raise ValueError("ADX cannot be ready before C27")
            if self.samples >= 28:
                if self.adx is None:
                    raise ValueError("ADX is required from C27 onward")
                if self.dx_seed_count != _PERIOD or self.dx_seed_sum != 0:
                    raise ValueError("Ready ADX state must have completed and cleared its DX seed")


class Adx14:
    """Incremental Wilder ADX(14) with the frozen Gate 1 indexing convention."""

    def __init__(self, *, state: AdxState | None = None) -> None:
        state = state or AdxState(
            samples=0,
            previous_high=None,
            previous_low=None,
            previous_close=None,
            seed_tr_sum=_ZERO,
            seed_plus_dm_sum=_ZERO,
            seed_minus_dm_sum=_ZERO,
            smoothed_tr=None,
            smoothed_plus_dm=None,
            smoothed_minus_dm=None,
            dx_seed_sum=_ZERO,
            dx_seed_count=0,
            adx=None,
        )
        self._state = state

    @property
    def samples(self) -> int:
        return self._state.samples

    @property
    def ready(self) -> bool:
        return self._state.adx is not None

    @property
    def value(self) -> Decimal | None:
        return self._state.adx

    def snapshot(self) -> AdxState:
        return self._state

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> AdxValues:
        for name, value in (("high", high), ("low", low), ("close", close)):
            _require_decimal(value, name=name)
        if high < low:
            raise ValueError("ADX high must be greater than or equal to low")

        s = self._state
        if s.samples == 0:
            self._state = AdxState(
                samples=1,
                previous_high=high,
                previous_low=low,
                previous_close=close,
                seed_tr_sum=_ZERO,
                seed_plus_dm_sum=_ZERO,
                seed_minus_dm_sum=_ZERO,
                smoothed_tr=None,
                smoothed_plus_dm=None,
                smoothed_minus_dm=None,
                dx_seed_sum=_ZERO,
                dx_seed_count=0,
                adx=None,
            )
            return AdxValues(None, None, None, None, None, None, None)

        assert s.previous_high is not None
        assert s.previous_low is not None
        assert s.previous_close is not None

        up_move = high - s.previous_high
        down_move = s.previous_low - low
        plus_dm = up_move if up_move > down_move and up_move > 0 else _ZERO
        minus_dm = down_move if down_move > up_move and down_move > 0 else _ZERO
        tr = max(high - low, abs(high - s.previous_close), abs(low - s.previous_close))
        samples = s.samples + 1

        if samples <= _PERIOD + 1:
            seed_tr = s.seed_tr_sum + tr
            seed_plus = s.seed_plus_dm_sum + plus_dm
            seed_minus = s.seed_minus_dm_sum + minus_dm
            if samples < _PERIOD + 1:
                self._state = AdxState(
                    samples=samples,
                    previous_high=high,
                    previous_low=low,
                    previous_close=close,
                    seed_tr_sum=seed_tr,
                    seed_plus_dm_sum=seed_plus,
                    seed_minus_dm_sum=seed_minus,
                    smoothed_tr=None,
                    smoothed_plus_dm=None,
                    smoothed_minus_dm=None,
                    dx_seed_sum=_ZERO,
                    dx_seed_count=0,
                    adx=None,
                )
                return AdxValues(tr, plus_dm, minus_dm, None, None, None, None)
            smoothed_tr = seed_tr
            smoothed_plus = seed_plus
            smoothed_minus = seed_minus
        else:
            assert s.smoothed_tr is not None
            assert s.smoothed_plus_dm is not None
            assert s.smoothed_minus_dm is not None
            period = Decimal(_PERIOD)
            smoothed_tr = s.smoothed_tr - (s.smoothed_tr / period) + tr
            smoothed_plus = s.smoothed_plus_dm - (s.smoothed_plus_dm / period) + plus_dm
            smoothed_minus = s.smoothed_minus_dm - (s.smoothed_minus_dm / period) + minus_dm

        plus_di, minus_di, dx = _directional_values(smoothed_tr, smoothed_plus, smoothed_minus)

        adx = s.adx
        dx_seed_sum = s.dx_seed_sum
        dx_seed_count = s.dx_seed_count
        if adx is None:
            dx_seed_sum += dx
            dx_seed_count += 1
            if dx_seed_count == _PERIOD:
                adx = dx_seed_sum / Decimal(_PERIOD)
                dx_seed_sum = _ZERO
        else:
            adx = ((adx * Decimal(_PERIOD - 1)) + dx) / Decimal(_PERIOD)

        self._state = AdxState(
            samples=samples,
            previous_high=high,
            previous_low=low,
            previous_close=close,
            seed_tr_sum=_ZERO,
            seed_plus_dm_sum=_ZERO,
            seed_minus_dm_sum=_ZERO,
            smoothed_tr=smoothed_tr,
            smoothed_plus_dm=smoothed_plus,
            smoothed_minus_dm=smoothed_minus,
            dx_seed_sum=dx_seed_sum,
            dx_seed_count=dx_seed_count,
            adx=adx,
        )
        return AdxValues(tr, plus_dm, minus_dm, plus_di, minus_di, dx, adx)


def _directional_values(
    smoothed_tr: Decimal,
    smoothed_plus_dm: Decimal,
    smoothed_minus_dm: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    if smoothed_tr == 0:
        plus_di = minus_di = _ZERO
    else:
        plus_di = _HUNDRED * smoothed_plus_dm / smoothed_tr
        minus_di = _HUNDRED * smoothed_minus_dm / smoothed_tr
    denominator = plus_di + minus_di
    dx = _ZERO if denominator == 0 else _HUNDRED * abs(plus_di - minus_di) / denominator
    return plus_di, minus_di, dx


def _require_decimal(value: Decimal, *, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"ADX {name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"ADX {name} must be finite")


def _require_optional_decimal(value: Decimal | None, *, name: str) -> None:
    if value is not None:
        _require_decimal(value, name=name)
