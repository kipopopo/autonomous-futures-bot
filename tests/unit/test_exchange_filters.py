from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.data.exchange_filters import (
    ExchangeFilterViolation,
    build_exchange_filter_snapshot,
    read_exchange_filter_snapshot,
    validate_order_filters,
    write_exchange_filter_snapshot,
)
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.transport import (
    BinancePublicExchangeInfoFetcher,
    TransportTelemetry,
)

OBSERVED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _exchange_info_payload(*, status: str = "TRADING") -> dict[str, object]:
    return {
        "timezone": "UTC",
        "serverTime": 1786104000000,
        "assets": [{"asset": "USDT", "marginAvailable": True, "autoAssetExchange": "-1"}],
        "symbols": [
            {
                "symbol": "ETHUSDT",
                "pair": "ETHUSDT",
                "contractType": "PERPETUAL",
                "status": status,
                "baseAsset": "ETH",
                "quoteAsset": "USDT",
                "settleAsset": "USDT",
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.01",
                        "maxPrice": "1000000",
                        "tickSize": "0.01",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "100000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "100000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "MIN_NOTIONAL",
                        "notional": "5",
                        "applyToMarket": True,
                    },
                ],
            },
            {
                "symbol": "BTCUSDT",
                "pair": "BTCUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "settleAsset": "USDT",
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.1",
                        "maxPrice": "1000000",
                        "tickSize": "0.1",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "100000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "100000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "NOTIONAL",
                        "minNotional": "5",
                        "maxNotional": "1000000",
                        "applyMinToMarket": True,
                        "applyMaxToMarket": False,
                    },
                ],
            },
        ],
    }


def test_exchange_info_fetcher_uses_unsigned_public_request() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    payload = _exchange_info_payload()

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append((path, params))
        return payload

    telemetry = TransportTelemetry()
    fetched = BinancePublicExchangeInfoFetcher(get_json=get_json, telemetry=telemetry)()

    assert fetched == payload
    assert calls == [("/fapi/v1/exchangeInfo", {})]
    assert telemetry.snapshot().success_count == 1


def test_snapshot_is_sorted_hashed_without_observation_time_and_write_once(
    tmp_path: Path,
) -> None:
    first = build_exchange_filter_snapshot(
        _exchange_info_payload(),
        symbols=("BTCUSDT", "ETHUSDT"),
        observed_at=OBSERVED_AT,
    )
    second = build_exchange_filter_snapshot(
        _exchange_info_payload(),
        symbols=("ETHUSDT", "BTCUSDT"),
        observed_at=OBSERVED_AT.replace(hour=13),
    )

    assert [item.symbol for item in first.symbols] == ["BTCUSDT", "ETHUSDT"]
    assert first.snapshot_hash == second.snapshot_hash
    assert first.symbols[0].price_tick_size == Decimal("0.1")
    assert first.symbols[1].min_notional == Decimal("5")

    path = tmp_path / "exchange-filters.json"
    write_exchange_filter_snapshot(path, first)
    assert read_exchange_filter_snapshot(path) == first
    assert write_exchange_filter_snapshot(path, first) == first


def test_snapshot_tampering_is_rejected(tmp_path: Path) -> None:
    snapshot = build_exchange_filter_snapshot(
        _exchange_info_payload(), symbols=("BTCUSDT",), observed_at=OBSERVED_AT
    )
    path = tmp_path / "exchange-filters.json"
    write_exchange_filter_snapshot(path, snapshot)
    path.write_text(
        path.read_text(encoding="utf-8").replace("BTCUSDT", "ETHUSDT"), encoding="utf-8"
    )

    with pytest.raises(Exception, match="hash mismatch"):
        read_exchange_filter_snapshot(path)


def test_runtime_filter_validation_accepts_aligned_limit_order() -> None:
    snapshot = build_exchange_filter_snapshot(
        _exchange_info_payload(), symbols=("BTCUSDT",), observed_at=OBSERVED_AT
    )

    validate_order_filters(
        snapshot,
        symbol="BTCUSDT",
        order_type="LIMIT",
        reference_price=Decimal("50000.1"),
        quantity=Decimal("0.001"),
    )


def test_runtime_filter_validation_rejects_status_tick_step_and_notional() -> None:
    status_payload = _exchange_info_payload()
    status_payload["symbols"][1]["status"] = "SETTLING"  # type: ignore[index]
    cases = [
        ("status", status_payload, Decimal("50000.1"), Decimal("0.001")),
        ("tick", _exchange_info_payload(), Decimal("50000.11"), Decimal("0.001")),
        ("step", _exchange_info_payload(), Decimal("50000.1"), Decimal("0.0015")),
        ("notional", _exchange_info_payload(), Decimal("1000.0"), Decimal("0.001")),
    ]
    for reason, payload, price, quantity in cases:
        current = build_exchange_filter_snapshot(
            payload, symbols=("BTCUSDT",), observed_at=OBSERVED_AT
        )
        with pytest.raises(ExchangeFilterViolation, match=reason):
            validate_order_filters(
                current,
                symbol="BTCUSDT",
                order_type="LIMIT",
                reference_price=price,
                quantity=quantity,
            )


def test_snapshot_requires_requested_symbol_and_required_filters() -> None:
    with pytest.raises(DataQualityError, match="symbol not found"):
        build_exchange_filter_snapshot(
            _exchange_info_payload(), symbols=("SOLUSDT",), observed_at=OBSERVED_AT
        )

    payload = _exchange_info_payload()
    payload["symbols"][0]["filters"] = []  # type: ignore[index]
    with pytest.raises(DataQualityError, match="PRICE_FILTER"):
        build_exchange_filter_snapshot(payload, symbols=("ETHUSDT",), observed_at=OBSERVED_AT)


def test_snapshot_uses_margin_asset_when_settle_asset_is_absent() -> None:
    payload = _exchange_info_payload()
    symbol = payload["symbols"][0]  # type: ignore[index]
    symbol.pop("settleAsset")
    symbol["marginAsset"] = "USDT"

    snapshot = build_exchange_filter_snapshot(
        payload, symbols=("ETHUSDT",), observed_at=OBSERVED_AT
    )

    assert snapshot.symbols[0].settle_asset == "USDT"
