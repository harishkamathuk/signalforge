"""Typed indicator requirements and immutable completed-candle values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import CandleInterval


class IndicatorKind(StrEnum):
    """Supported canonical indicator implementations."""

    EMA = "ema"
    RSI = "rsi"
    ADX = "adx"
    MACD = "macd"


@dataclass(frozen=True, slots=True)
class EmaRequirement:
    """Request one canonical EMA period."""

    period: int

    def __post_init__(self) -> None:
        if isinstance(self.period, bool) or not isinstance(self.period, int):
            raise TypeError("EMA requirement period must be an integer")
        if self.period <= 0:
            raise ValueError("EMA requirement period must be strictly positive")


@dataclass(frozen=True, slots=True)
class RsiRequirement:
    """Request the supported canonical RSI implementation."""

    period: int = 14

    def __post_init__(self) -> None:
        if self.period != 14:
            raise ValueError("Only canonical RSI(14) is supported")


@dataclass(frozen=True, slots=True)
class AdxRequirement:
    """Request the supported canonical ADX implementation."""

    period: int = 14

    def __post_init__(self) -> None:
        if self.period != 14:
            raise ValueError("Only canonical ADX(14) is supported")


@dataclass(frozen=True, slots=True)
class MacdRequirement:
    """Request the supported canonical MACD implementation."""

    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def __post_init__(self) -> None:
        if (self.fast_period, self.slow_period, self.signal_period) != (12, 26, 9):
            raise ValueError("Only canonical MACD(12,26,9) is supported")


type IndicatorRequirement = EmaRequirement | RsiRequirement | AdxRequirement | MacdRequirement


def indicator_requirement_key(requirement: IndicatorRequirement) -> str:
    """Return the deterministic identity key for one supported requirement."""

    if isinstance(requirement, EmaRequirement):
        return f"ema:{requirement.period}"
    if isinstance(requirement, RsiRequirement):
        return f"rsi:{requirement.period}"
    if isinstance(requirement, AdxRequirement):
        return f"adx:{requirement.period}"
    if isinstance(requirement, MacdRequirement):
        return (
            f"macd:{requirement.fast_period}:{requirement.slow_period}:"
            f"{requirement.signal_period}"
        )
    raise TypeError(f"Unsupported indicator requirement type: {type(requirement).__name__}")


@dataclass(frozen=True, slots=True)
class IndicatorRequirements:
    """Canonical deterministic set of supported indicator requirements."""

    items: tuple[IndicatorRequirement, ...]

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("Indicator requirements must not be empty")
        by_key: dict[str, IndicatorRequirement] = {}
        for requirement in self.items:
            key = indicator_requirement_key(requirement)
            by_key.setdefault(key, requirement)
        canonical = tuple(by_key[key] for key in sorted(by_key))
        object.__setattr__(self, "items", canonical)

    @classmethod
    def of(cls, *requirements: IndicatorRequirement) -> IndicatorRequirements:
        """Build a canonical requirement set independent of declaration order."""

        return cls(tuple(requirements))

    @property
    def keys(self) -> tuple[str, ...]:
        """Return deterministic requirement keys suitable for compatibility checks."""

        return tuple(indicator_requirement_key(item) for item in self.items)


@dataclass(frozen=True, slots=True)
class MacdIndicatorValues:
    """Typed values emitted by one MACD requirement."""

    line: Decimal | None
    signal: Decimal | None
    histogram: Decimal | None

    @property
    def ready(self) -> bool:
        """Return whether the complete MACD tuple is ready."""

        return self.line is not None and self.signal is not None and self.histogram is not None


@dataclass(frozen=True, slots=True)
class IndicatorReading:
    """One requirement and its current value payload."""

    requirement: IndicatorRequirement
    value: Decimal | None
    signal: Decimal | None = None
    histogram: Decimal | None = None

    def __post_init__(self) -> None:
        for name, candidate in (
            ("value", self.value),
            ("signal", self.signal),
            ("histogram", self.histogram),
        ):
            if candidate is not None:
                if not isinstance(candidate, Decimal):
                    raise TypeError(f"Indicator reading {name} must be a Decimal")
                if not candidate.is_finite():
                    raise ValueError(f"Indicator reading {name} must be finite")
        if not isinstance(self.requirement, MacdRequirement) and (
            self.signal is not None or self.histogram is not None
        ):
            raise ValueError("Only MACD readings may include signal/histogram values")

    @property
    def ready(self) -> bool:
        """Return readiness for this requirement only."""

        if isinstance(self.requirement, MacdRequirement):
            return (
                self.value is not None
                and self.signal is not None
                and self.histogram is not None
            )
        return self.value is not None


@dataclass(frozen=True, slots=True, init=False)
class IndicatorSnapshot:
    """Indicator values produced for one completed canonical candle.

    Readiness is requirement-specific: the snapshot is fully ready only when
    every declared requirement is ready. Missing requirements raise rather
    than silently appearing as an unready value.
    """

    instrument_id: InstrumentId
    interval: CandleInterval
    calculation_version: str
    readings: tuple[IndicatorReading, ...]

    def __init__(
        self,
        instrument_id: InstrumentId,
        interval: CandleInterval,
        calculation_version: str,
        readings: tuple[IndicatorReading, ...] | None = None,
        *,
        ready: bool | None = None,
        ema9: Decimal | None = None,
        ema20: Decimal | None = None,
        ema50: Decimal | None = None,
        rsi14: Decimal | None = None,
        adx14: Decimal | None = None,
        macd_line: Decimal | None = None,
        macd_signal: Decimal | None = None,
        macd_histogram: Decimal | None = None,
    ) -> None:
        """Create generic readings, accepting the legacy V1 constructor during migration."""

        if readings is not None and ready is not None:
            raise ValueError("Explicit readings must not also provide legacy ready")
        if readings is None:
            legacy_values = (
                ema9,
                ema20,
                ema50,
                rsi14,
                adx14,
                macd_line,
                macd_signal,
                macd_histogram,
            )
            if ready is not None and not isinstance(ready, bool):
                raise TypeError("IndicatorSnapshot ready must be a boolean")
            if ready and any(value is None for value in legacy_values):
                raise ValueError("Ready IndicatorSnapshot requires all indicator values")
            legacy_readings = (
                IndicatorReading(AdxRequirement(14), adx14),
                IndicatorReading(EmaRequirement(9), ema9),
                IndicatorReading(EmaRequirement(20), ema20),
                IndicatorReading(EmaRequirement(50), ema50),
                IndicatorReading(
                    MacdRequirement(12, 26, 9),
                    macd_line,
                    macd_signal,
                    macd_histogram,
                ),
                IndicatorReading(RsiRequirement(14), rsi14),
            )
            readings = tuple(
                sorted(
                    legacy_readings,
                    key=lambda item: indicator_requirement_key(item.requirement),
                )
            )
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "calculation_version", calculation_version)
        object.__setattr__(self, "readings", readings)
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.calculation_version or not self.calculation_version.strip():
            raise ValueError("IndicatorSnapshot calculation_version must not be empty")
        if not self.readings:
            raise ValueError("IndicatorSnapshot requires at least one reading")
        keys = tuple(indicator_requirement_key(item.requirement) for item in self.readings)
        if len(keys) != len(set(keys)):
            raise ValueError("IndicatorSnapshot contains duplicate requirements")
        if keys != tuple(sorted(keys)):
            raise ValueError("IndicatorSnapshot readings must use canonical requirement order")

    @property
    def requirements(self) -> IndicatorRequirements:
        """Return the canonical requirements represented by this snapshot."""

        return IndicatorRequirements(tuple(item.requirement for item in self.readings))

    @property
    def ready(self) -> bool:
        """Return whether all declared requirements are ready."""

        return all(item.ready for item in self.readings)

    def reading(self, requirement: IndicatorRequirement) -> IndicatorReading:
        """Return one required reading or fail explicitly when it is absent."""

        key = indicator_requirement_key(requirement)
        for item in self.readings:
            if indicator_requirement_key(item.requirement) == key:
                return item
        raise KeyError(f"Indicator requirement not present in snapshot: {key}")

    def ema(self, period: int) -> Decimal | None:
        """Return EMA(period), preserving unready as None."""

        return self.reading(EmaRequirement(period)).value

    def rsi(self, period: int = 14) -> Decimal | None:
        """Return canonical RSI(period), preserving unready as None."""

        return self.reading(RsiRequirement(period)).value

    def adx(self, period: int = 14) -> Decimal | None:
        """Return canonical ADX(period), preserving unready as None."""

        return self.reading(AdxRequirement(period)).value

    def macd(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> MacdIndicatorValues:
        """Return canonical MACD values for the requested supported specification."""

        reading = self.reading(MacdRequirement(fast_period, slow_period, signal_period))
        return MacdIndicatorValues(reading.value, reading.signal, reading.histogram)

    # Compatibility properties keep Strategy V1 diagnostics unchanged while
    # shared runtime state is requirement-driven.
    @property
    def ema9(self) -> Decimal | None:
        return self.ema(9)

    @property
    def ema20(self) -> Decimal | None:
        return self.ema(20)

    @property
    def ema50(self) -> Decimal | None:
        return self.ema(50)

    @property
    def rsi14(self) -> Decimal | None:
        return self.rsi(14)

    @property
    def adx14(self) -> Decimal | None:
        return self.adx(14)

    @property
    def macd_line(self) -> Decimal | None:
        return self.macd().line

    @property
    def macd_signal(self) -> Decimal | None:
        return self.macd().signal

    @property
    def macd_histogram(self) -> Decimal | None:
        return self.macd().histogram
