"""OpenAlgo adapter boundary for configuration and startup preflight."""

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import (
    OpenAlgoPreflightResult,
    OpenAlgoPreflightStatus,
    preflight,
)
from signalforge.adapters.openalgo.reference import (
    OpenAlgoReferenceAmbiguous,
    OpenAlgoReferenceContradiction,
    OpenAlgoReferenceError,
    OpenAlgoReferenceNotFound,
    OpenAlgoReferenceProvenance,
    OpenAlgoSubscriptionIdentity,
    ResolvedOpenAlgoInstrument,
    resolve_nse_equity_reference,
)

__all__ = [
    "OpenAlgoConfig",
    "OpenAlgoPreflightResult",
    "OpenAlgoPreflightStatus",
    "OpenAlgoReferenceAmbiguous",
    "OpenAlgoReferenceContradiction",
    "OpenAlgoReferenceError",
    "OpenAlgoReferenceNotFound",
    "OpenAlgoReferenceProvenance",
    "OpenAlgoSubscriptionIdentity",
    "ResolvedOpenAlgoInstrument",
    "preflight",
    "resolve_nse_equity_reference",
]
