"""Offline-testable public read-only testnet adapter contract."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

from pydantic import Field

from .domain.contracts import DomainModel
from .testnet import TESTNET_REST_BASE_URL, classify_testnet_error, validate_testnet_rest_url


class TestnetResponse(DomainModel):
    status_code: int = Field(ge=100, le=599, strict=True)
    body: object


class TestnetExchangeSymbol(DomainModel):
    symbol: str = Field(min_length=1)
    status: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    contract_type: str = Field(min_length=1)


class TestnetExchangeInfo(DomainModel):
    symbols: tuple[TestnetExchangeSymbol, ...] = Field(min_length=1)


class TestnetReadOnlyError(ValueError):
    def __init__(self, message: str, *, disposition: str) -> None:
        super().__init__(message)
        self.disposition = disposition


TestnetTransport = Callable[[str, str, dict[str, str]], TestnetResponse]


def public_testnet_transport(
    method: str,
    url: str,
    query: dict[str, str],
) -> TestnetResponse:
    """Perform one allow-listed public GET; it never retries or sends credentials."""
    if method != "GET":
        raise ValueError("public testnet transport permits GET only")
    validated_url = validate_testnet_rest_url(url)
    if query:
        validated_url += "?" + urlencode(sorted(query.items()))
    request = urllib.request.Request(
        validated_url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return TestnetResponse(
                status_code=response.status,
                body=json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as exc:
        try:
            body: object = json.loads(exc.read().decode("utf-8"))
        except json.JSONDecodeError:
            body = {"msg": str(exc)}
        except UnicodeDecodeError:
            body = {"msg": str(exc)}
        return TestnetResponse(status_code=exc.code, body=body)


class TestnetReadOnlyClient:
    """Public exchange-info contract with transport supplied by the caller."""

    def __init__(self, transport: TestnetTransport, *, base_url: str) -> None:
        if base_url != TESTNET_REST_BASE_URL:
            raise ValueError("testnet base URL must be the official USD-M demo host")
        self._transport = transport
        self._base_url = base_url

    def get_exchange_info(self) -> TestnetExchangeInfo:
        response = self._transport(
            "GET",
            f"{self._base_url}/fapi/v1/exchangeInfo",
            {},
        )
        if response.status_code != 200:
            message = ""
            if isinstance(response.body, Mapping):
                raw_message = response.body.get("msg", "")
                message = raw_message if isinstance(raw_message, str) else str(raw_message)
            disposition = classify_testnet_error(response.status_code, message)
            raise TestnetReadOnlyError(
                f"read-only testnet request requires {disposition}",
                disposition=disposition,
            )
        if not isinstance(response.body, Mapping):
            raise TestnetReadOnlyError(
                "malformed testnet exchange-info response",
                disposition="reject",
            )
        raw_symbols = response.body.get("symbols")
        if not isinstance(raw_symbols, list):
            raise TestnetReadOnlyError(
                "malformed testnet exchange-info symbols",
                disposition="reject",
            )
        symbols: list[TestnetExchangeSymbol] = []
        try:
            for raw_symbol in raw_symbols:
                if not isinstance(raw_symbol, Mapping):
                    raise ValueError("symbol row is not an object")
                symbols.append(
                    TestnetExchangeSymbol(
                        symbol=raw_symbol["symbol"],
                        status=raw_symbol["status"],
                        base_asset=raw_symbol["baseAsset"],
                        quote_asset=raw_symbol["quoteAsset"],
                        contract_type=raw_symbol["contractType"],
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise TestnetReadOnlyError(
                "malformed testnet exchange-info symbol row",
                disposition="reject",
            ) from exc
        return TestnetExchangeInfo(symbols=tuple(symbols))

    def get_symbol(self, symbol: str) -> TestnetExchangeSymbol:
        info = self.get_exchange_info()
        for item in info.symbols:
            if item.symbol == symbol and item.contract_type == "PERPETUAL":
                return item
        raise ValueError(f"testnet symbol unavailable: {symbol}")
