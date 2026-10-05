from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from signalforge.adapters.openalgo.config import OpenAlgoConfig
from signalforge.adapters.openalgo.reference import (
    OpenAlgoReferenceAmbiguous,
    OpenAlgoReferenceContradiction,
    OpenAlgoReferenceError,
    OpenAlgoReferenceNotFound,
    resolve_nse_equity_reference,
)
from signalforge.adapters.openalgo.transport import (
    OpenAlgoHttpResponse,
    OpenAlgoTransportUnavailable,
)
from signalforge.domain.ids import InstrumentId

CONFIG = OpenAlgoConfig(host="http://127.0.0.1:5000", api_key="secret")
OBSERVED_AT = datetime(2026, 10, 5, 9, 15, tzinfo=UTC)
TRADING_DATE = date(2026, 10, 5)


@dataclass
class FakeTransport:
    symbol_response: OpenAlgoHttpResponse | None = None
    search_response: OpenAlgoHttpResponse | None = None
    failure: Exception | None = None

    def post_json(
        self,
        *,
        path: str,
        payload: dict[str, object],
        connect_timeout_seconds: float,
        request_timeout_seconds: float,
    ) -> OpenAlgoHttpResponse:
        assert payload["apikey"] == "secret"
        assert connect_timeout_seconds == CONFIG.connect_timeout_seconds
        assert request_timeout_seconds == CONFIG.request_timeout_seconds
        if self.failure is not None:
            raise self.failure
        if path == "/api/v1/symbol":
            assert payload["symbol"] == "RELIANCE"
            assert payload["exchange"] == "NSE"
            assert self.symbol_response is not None
            return self.symbol_response
        if path == "/api/v1/search":
            assert payload["query"] == "RELIANCE"
            assert payload["exchange"] == "NSE"
            assert self.search_response is not None
            return self.search_response
        raise AssertionError(f"unexpected path: {path}")


def response(body: str, *, status: int = 200) -> OpenAlgoHttpResponse:
    return OpenAlgoHttpResponse(
        status_code=status,
        body=body.encode("utf-8"),
        content_type="application/json",
    )


def symbol_response(
    *,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    instrument_type: str = "EQ",
    tick_size: str = "0.05",
) -> OpenAlgoHttpResponse:
    return response(
        '{"status":"success","data":{'
        f'"symbol":"{symbol}","exchange":"{exchange}",'
        f'"instrumenttype":"{instrument_type}","tick_size":{tick_size},'
        '"token":"2885","brsymbol":"RELIANCE","brexchange":"NSE"'
        "}}"
    )


def search_response(*rows: str) -> OpenAlgoHttpResponse:
    return response('{"status":"success","data":[' + ",".join(rows) + "]}")


def row(
    *,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    instrument_type: str = "EQ",
    tick_size: str = "0.05",
    token: str = "2885",
) -> str:
    return (
        "{"
        f'"symbol":"{symbol}","exchange":"{exchange}",'
        f'"instrumenttype":"{instrument_type}","tick_size":{tick_size},'
        f'"token":"{token}","brsymbol":"RELIANCE","brexchange":"NSE"'
        "}"
    )


def resolve(
    *,
    symbol: OpenAlgoHttpResponse | None = None,
    search: OpenAlgoHttpResponse | None = None,
    trading_date: date = TRADING_DATE,
) -> object:
    return resolve_nse_equity_reference(
        config=CONFIG,
        instrument_id=InstrumentId("NSE:RELIANCE"),
        trading_date=trading_date,
        observed_at=OBSERVED_AT,
        transport=FakeTransport(
            symbol_response=symbol or symbol_response(),
            search_response=search or search_response(row()),
        ),
    )


def test_exact_nse_equity_resolution_builds_canonical_reference_snapshot() -> None:
    resolved = resolve()

    assert resolved.instrument_id == InstrumentId("NSE:RELIANCE")
    assert resolved.instrument.instrument_id == resolved.instrument_id
    assert resolved.instrument.exchange == "NSE"
    assert resolved.instrument.symbol == "RELIANCE"
    assert resolved.subscription.symbol == "RELIANCE"
    assert resolved.subscription.exchange == "NSE"
    assert resolved.tick_size_schedule.instrument_id == resolved.instrument_id
    assert resolved.tick_size_schedule.tick_size_on(TRADING_DATE).value == Decimal("0.05")

    rule = resolved.tick_size_schedule.rules[0]
    assert rule.effective_from == TRADING_DATE
    assert rule.effective_to == TRADING_DATE
    assert resolved.provenance.trading_date == TRADING_DATE
    assert resolved.provenance.observed_at == OBSERVED_AT
    assert resolved.provenance.sources == ("/api/v1/symbol", "/api/v1/search")
    assert resolved.provenance.provider_token == "2885"
    assert resolved.provenance.broker_symbol == "RELIANCE"
    assert resolved.provenance.broker_exchange == "NSE"


def test_decimal_tick_precision_is_preserved_without_binary_float_conversion() -> None:
    precise = "0.012345678901234567890123456789"
    resolved = resolve(
        symbol=symbol_response(tick_size=precise),
        search=search_response(row(tick_size=precise)),
    )

    assert resolved.tick_size_schedule.tick_size_on(TRADING_DATE).value == Decimal(precise)


def test_trading_date_is_bound_to_one_day_only() -> None:
    next_date = date(2026, 10, 6)
    resolved = resolve(trading_date=next_date)

    rule = resolved.tick_size_schedule.rules[0]
    assert rule.effective_from == next_date
    assert rule.effective_to == next_date
    assert resolved.provenance.trading_date == next_date


def test_reference_observation_must_match_trading_date_in_ist() -> None:
    with pytest.raises(ValueError, match="observation date"):
        resolve_nse_equity_reference(
            config=CONFIG,
            instrument_id=InstrumentId("NSE:RELIANCE"),
            trading_date=date(2026, 10, 6),
            observed_at=OBSERVED_AT,
            transport=FakeTransport(),
        )


def test_fuzzy_search_rows_do_not_become_authoritative() -> None:
    resolved = resolve(
        search=search_response(
            row(symbol="RELIANCEPP", token="other"),
            row(),
            row(symbol="RELIANCEBE", token="other-2"),
        )
    )

    assert resolved.instrument_id == InstrumentId("NSE:RELIANCE")


def test_missing_exact_search_match_fails() -> None:
    with pytest.raises(OpenAlgoReferenceNotFound):
        resolve(search=search_response(row(symbol="RELIANCEPP")))


def test_duplicate_exact_search_matches_are_ambiguous_even_if_identical() -> None:
    with pytest.raises(OpenAlgoReferenceAmbiguous):
        resolve(search=search_response(row(), row()))


@pytest.mark.parametrize(
    ("symbol", "exchange", "instrument_type"),
    [
        ("TCS", "NSE", "EQ"),
        ("RELIANCE", "BSE", "EQ"),
        ("RELIANCE", "NSE", "FUT"),
    ],
)
def test_symbol_surface_must_exactly_match_configured_nse_equity(
    symbol: str,
    exchange: str,
    instrument_type: str,
) -> None:
    with pytest.raises(OpenAlgoReferenceContradiction):
        resolve(
            symbol=symbol_response(
                symbol=symbol,
                exchange=exchange,
                instrument_type=instrument_type,
            )
        )


@pytest.mark.parametrize("provider_symbol", [" RELIANCE", "RELIANCE ", "reliance"])
def test_provider_symbol_is_not_silently_normalized(provider_symbol: str) -> None:
    expected_error = (
        OpenAlgoReferenceError
        if provider_symbol != provider_symbol.strip()
        else OpenAlgoReferenceContradiction
    )
    with pytest.raises(expected_error):
        resolve(symbol=symbol_response(symbol=provider_symbol))


def test_symbol_and_search_tick_size_contradiction_fails_closed() -> None:
    with pytest.raises(OpenAlgoReferenceContradiction):
        resolve(
            symbol=symbol_response(tick_size="0.05"),
            search=search_response(row(tick_size="5")),
        )


@pytest.mark.parametrize("tick_size", ["0", "-0.05", "NaN"])
def test_non_positive_or_non_finite_tick_size_is_rejected(tick_size: str) -> None:
    with pytest.raises(OpenAlgoReferenceError):
        resolve(
            symbol=symbol_response(tick_size=tick_size),
            search=search_response(row(tick_size=tick_size)),
        )


def test_missing_tick_size_is_rejected() -> None:
    malformed = response(
        '{"status":"success","data":{'
        '"symbol":"RELIANCE","exchange":"NSE","instrumenttype":"EQ"'
        "}}"
    )

    with pytest.raises(OpenAlgoReferenceError):
        resolve(symbol=malformed)


@pytest.mark.parametrize(
    "provider_response",
    [
        response("not-json"),
        response("[]"),
        response('{"status":"error","message":"unavailable"}'),
        OpenAlgoHttpResponse(200, b'{"status":"success","data":{}}', "text/html"),
    ],
)
def test_malformed_symbol_provider_responses_fail_closed(
    provider_response: OpenAlgoHttpResponse,
) -> None:
    with pytest.raises(OpenAlgoReferenceError):
        resolve(symbol=provider_response)


@pytest.mark.parametrize(
    "configured",
    [
        "BSE:RELIANCE",
        "NSE:reliance",
        "NSE: RELIANCE",
        "NSE:",
        "NSE:RELIANCE:EQ",
    ],
)
def test_configured_identity_must_already_be_canonical(configured: str) -> None:
    with pytest.raises(ValueError):
        resolve_nse_equity_reference(
            config=CONFIG,
            instrument_id=InstrumentId(configured),
            trading_date=TRADING_DATE,
            observed_at=OBSERVED_AT,
            transport=FakeTransport(),
        )


def test_transport_failure_is_adapter_owned() -> None:
    with pytest.raises(OpenAlgoReferenceError, match="unreachable"):
        resolve_nse_equity_reference(
            config=CONFIG,
            instrument_id=InstrumentId("NSE:RELIANCE"),
            trading_date=TRADING_DATE,
            observed_at=OBSERVED_AT,
            transport=FakeTransport(
                failure=OpenAlgoTransportUnavailable("network down"),
            ),
        )
