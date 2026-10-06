from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.history import (
    OpenAlgoHistoryValidationError,
    fetch_openalgo_history,
)
from signalforge.adapters.openalgo.transport import OpenAlgoHttpResponse
from signalforge.domain.ids import InstrumentId
from signalforge.domain.time import IST


class RecordingTransport:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def post_json(self, **kwargs: object) -> OpenAlgoHttpResponse:
        self.calls.append(kwargs)
        return OpenAlgoHttpResponse(
            status_code=200,
            body=json.dumps({"status": "success", "data": self.rows}).encode(),
            content_type="application/json",
        )


def _row(at: datetime, *, close: str = "100.5") -> dict[str, object]:
    return {
        "timestamp": int(at.timestamp()),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": close,
        "volume": 100,
    }


def test_history_request_uses_exact_nse_symbol_and_five_minute_interval() -> None:
    transport = RecordingTransport(
        [_row(datetime(2026, 10, 1, 9, 15, tzinfo=IST))]
    )
    config = OpenAlgoConfig(
        host="http://127.0.0.1:5000",
        api_key="secret-key",
    )

    candles = fetch_openalgo_history(
        config=config,
        instrument_id=InstrumentId("NSE:RELIANCE"),
        start_date=datetime(2026, 10, 1).date(),
        end_date=datetime(2026, 10, 1).date(),
        transport=transport,
    )

    assert len(candles) == 1
    call = transport.calls[0]
    assert call["path"] == "/api/v1/history"
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["symbol"] == "RELIANCE"
    assert payload["exchange"] == "NSE"
    assert payload["interval"] == "5m"
    assert payload["apikey"] == "secret-key"
    assert candles[0].close.value == Decimal("100.5")


def test_history_rejects_duplicate_interval_without_synthesizing_continuity() -> None:
    at = datetime(2026, 10, 1, 9, 15, tzinfo=IST)
    transport = RecordingTransport([_row(at), _row(at)])
    config = OpenAlgoConfig(
        host="http://127.0.0.1:5000",
        api_key="secret-key",
    )

    with pytest.raises(OpenAlgoHistoryValidationError):
        fetch_openalgo_history(
            config=config,
            instrument_id=InstrumentId("NSE:RELIANCE"),
            start_date=at.date(),
            end_date=at.date(),
            transport=transport,
        )


def test_history_rejects_pre_market_row() -> None:
    at = datetime(2026, 10, 1, 9, 10, tzinfo=IST)
    transport = RecordingTransport([_row(at)])
    config = OpenAlgoConfig(
        host="http://127.0.0.1:5000",
        api_key="secret-key",
    )

    with pytest.raises(OpenAlgoHistoryValidationError, match="pre-market"):
        fetch_openalgo_history(
            config=config,
            instrument_id=InstrumentId("NSE:RELIANCE"),
            start_date=at.date(),
            end_date=at.date(),
            transport=transport,
        )
