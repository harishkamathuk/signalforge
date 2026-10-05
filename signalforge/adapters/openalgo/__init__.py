"""OpenAlgo adapter boundary for configuration and startup preflight."""

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.health import (
    OpenAlgoPreflightResult,
    OpenAlgoPreflightStatus,
    preflight,
)
from signalforge.adapters.openalgo.live_market_data import (
    OPENALGO_MARKET_DATA_SOURCE,
    OpenAlgoMarketDataAdapter,
    OpenAlgoMarketDataContinuityError,
    OpenAlgoMarketDataDisconnected,
    OpenAlgoMarketDataError,
    OpenAlgoMarketDataProtocolError,
)
from signalforge.adapters.openalgo.market_data_config import OpenAlgoMarketDataConfig
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
    "OPENALGO_MARKET_DATA_SOURCE",
    "OpenAlgoMarketDataAdapter",
    "OpenAlgoMarketDataConfig",
    "OpenAlgoMarketDataContinuityError",
    "OpenAlgoMarketDataDisconnected",
    "OpenAlgoMarketDataError",
    "OpenAlgoMarketDataProtocolError",
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
