"""OpenAlgo adapter boundary for configuration and startup preflight."""

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import (
    OpenAlgoPreflightResult,
    OpenAlgoPreflightStatus,
    preflight,
)

__all__ = [
    "OpenAlgoConfig",
    "OpenAlgoPreflightResult",
    "OpenAlgoPreflightStatus",
    "preflight",
]
