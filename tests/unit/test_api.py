from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.registry import (
    DatasetKind,
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)

START = datetime(2026, 8, 7, tzinfo=UTC)
END = START + timedelta(hours=1)
OBSERVED = datetime(2026, 8, 7, 12, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry(
    kind: DatasetKind,
    *,
    interval: str | None,
    time_start: datetime | None,
    time_end: datetime | None,
    content_hash: str,
) -> DatasetRegistryEntry:
    endpoints = {
        "kline": "/fapi/v1/klines",
        "mark_price": "/fapi/v1/markPriceKlines",
        "funding_rate": "/fapi/v1/fundingRate",
        "exchange_filters": "/fapi/v1/exchangeInfo",
    }
    return DatasetRegistryEntry(
        kind=kind,
        symbols=(SYMBOL,),
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        observed_at=OBSERVED,
        schema_version=f"{kind}-v1",
        content_hash=content_hash,
        artifact_ref=f"artifacts/{kind}.json",
        endpoint_path=endpoints[kind],
        provenance=("binance_public_rest", "unsigned", "api_fixture"),
    )


def _write_catalog(tmp_path: Path) -> tuple[Path, Path]:
    entries = (
        _entry(
            "kline",
            interval="5m",
            time_start=START,
            time_end=END - timedelta(minutes=5),
            content_hash="1" * 64,
        ),
        _entry(
            "kline",
            interval="15m",
            time_start=START - timedelta(minutes=15),
            time_end=END - timedelta(minutes=15),
            content_hash="2" * 64,
        ),
        _entry(
            "mark_price",
            interval="5m",
            time_start=START,
            time_end=END,
            content_hash="3" * 64,
        ),
        _entry(
            "funding_rate",
            interval=None,
            time_start=START - timedelta(hours=8),
            time_end=END + timedelta(hours=8),
            content_hash="4" * 64,
        ),
        _entry(
            "exchange_filters",
            interval=None,
            time_start=None,
            time_end=None,
            content_hash="5" * 64,
        ),
    )
    registry = build_dataset_registry(entries, created_at=OBSERVED)
    registry_path = tmp_path / "dataset-registry.json"
    write_dataset_registry(registry_path, registry)
    bundle = build_dataset_bundle(
        registry,
        symbols=(SYMBOL,),
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
    )
    bundle_path = tmp_path / "dataset-bundle.json"
    write_dataset_bundle(bundle_path, bundle)
    return bundle_path, registry_path


def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(send())


def test_health_declares_paper_safe_read_only_boundary(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "autonomous-futures-data-api",
        "paper_safe": True,
        "execution_authority": False,
    }
    assert _request(app, "POST", "/api/v1/dataset/bundle").status_code == 405
    assert _request(app, "GET", "/api/v1/order").status_code == 404


def test_rows_endpoint_is_get_only_and_fails_closed_without_catalog(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(
        app,
        "GET",
        "/api/v1/dataset/rows?kind=kline&symbol=BTCUSDT&interval=5m&start=2026-08-07T00:00:00Z&end=2026-08-07T00:05:00Z",
    )

    assert response.status_code == 503
    assert _request(app, "POST", "/api/v1/dataset/rows").status_code == 405


def test_bundle_endpoint_returns_verified_metadata_only(tmp_path: Path) -> None:
    bundle_path, registry_path = _write_catalog(tmp_path)
    app = create_app(bundle_path=bundle_path, registry_path=registry_path)

    response = _request(app, "GET", "/api/v1/dataset/bundle")
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["component_count"] == 5
    assert payload["bundle"]["context_interval"] == "15m"
    assert payload["bundle"]["bundle_hash"]
    assert "rows" not in payload
    assert "order" not in payload


def test_registry_endpoint_returns_verified_entries(tmp_path: Path) -> None:
    bundle_path, registry_path = _write_catalog(tmp_path)
    app = create_app(bundle_path=bundle_path, registry_path=registry_path)

    response = _request(app, "GET", "/api/v1/dataset/registry")
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert len(payload["registry"]["entries"]) == 5
    assert {entry["kind"] for entry in payload["registry"]["entries"]} == {
        "kline",
        "mark_price",
        "funding_rate",
        "exchange_filters",
    }


def test_api_fails_closed_on_tampered_bundle(tmp_path: Path) -> None:
    bundle_path, registry_path = _write_catalog(tmp_path)
    app = create_app(bundle_path=bundle_path, registry_path=registry_path)
    bundle_path.write_text(
        bundle_path.read_text(encoding="utf-8").replace('"bundle_hash": "', '"bundle_hash": "0'),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/dataset/bundle")
    assert response.status_code == 503
    assert response.json() == {"detail": "dataset catalog integrity verification failed"}


def test_api_serves_frontend_dist(tmp_path: Path) -> None:
    bundle_path, registry_path = _write_catalog(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_html = dist_dir / "index.html"
    index_html.write_text(
        "<!DOCTYPE html><html><body>Mission Control</body></html>",
        encoding="utf-8",
    )

    app = create_app(
        bundle_path=bundle_path,
        registry_path=registry_path,
        frontend_dist_path=dist_dir,
    )

    response = _request(app, "GET", "/")
    assert response.status_code == 200
    assert "Mission Control" in response.text


def test_market_prices_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json
    import urllib.request

    from autonomous_futures.api.app import TARGET_PERPETUAL_SYMBOLS, reset_live_market_cache

    reset_live_market_cache()

    def mock_urlopen(req: object, *args: object, **kwargs: object) -> io.BytesIO:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "ticker/price" in url:
            body = json.dumps(
                [
                    {"symbol": sym, "price": str(100.0 + idx)}
                    for idx, sym in enumerate(TARGET_PERPETUAL_SYMBOLS)
                ]
            )
        elif "premiumIndex" in url:
            body = json.dumps(
                [
                    {
                        "symbol": sym,
                        "markPrice": str(100.0 + idx),
                        "indexPrice": str(100.0 + idx),
                        "lastFundingRate": "0.0001",
                    }
                    for idx, sym in enumerate(TARGET_PERPETUAL_SYMBOLS)
                ]
            )
        else:
            body = json.dumps(
                [[idx * 3600000, "100", "101", "99", "100.5", "10"] for idx in range(210)]
            )
        return io.BytesIO(body.encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/market/prices")
    assert response.status_code == 200
    payload = response.json()
    assert "timestamp_ms" in payload
    assert "prices" in payload
    assert "last_prices" in payload
    assert "mark_prices" in payload
    assert "pair_tickers" in payload
    assert len(payload["pair_tickers"]) == 12
    assert all("last_price" in pt and "mark_price" in pt for pt in payload["pair_tickers"])
    assert "BTCUSDT" in payload["prices"]
    assert "ETHUSDT" in payload["prices"]
    assert "SOLUSDT" in payload["prices"]
    assert payload["prices"]["BTCUSDT"] > 0
    assert payload["prices"]["ETHUSDT"] > 0
    assert payload["prices"]["SOLUSDT"] > 0
    assert payload["last_prices"]["BTCUSDT"] > 0
    assert payload["mark_prices"]["BTCUSDT"] > 0
    assert "btc_macro" in payload
    assert "source" in payload


def test_market_klines_endpoint_default(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    response = _request(app, "GET", "/api/v1/market/klines")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "SOLUSDT"
    assert payload["interval"] == "15m"
    assert "candles" in payload
    assert len(payload["candles"]) > 0
    c0 = payload["candles"][0]
    assert "timestamp" in c0
    assert "open" in c0
    assert "high" in c0
    assert "low" in c0
    assert "close" in c0
    assert "volume" in c0
    assert c0["high"] >= c0["low"]


def test_market_klines_endpoint_custom_query(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    response = _request(app, "GET", "/api/v1/market/klines?symbol=BTCUSDT&interval=1h&limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["interval"] == "1h"
    assert len(payload["candles"]) == 50
    assert payload["count"] == 50


def test_market_klines_caching_5s_ttl(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    r1 = _request(app, "GET", "/api/v1/market/klines?symbol=ETHUSDT&interval=15m&limit=10")
    r2 = _request(app, "GET", "/api/v1/market/klines?symbol=ETHUSDT&interval=15m&limit=10")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["timestamp_ms"] == r2.json()["timestamp_ms"]
    assert r1.json()["candles"] == r2.json()["candles"]


def test_market_klines_offline_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request
    from urllib.error import URLError

    def mock_urlopen(*args: object, **kwargs: object) -> object:
        raise URLError("Network unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    # Tier 2: Local Parquet cache for known symbol/interval
    r_parquet = _request(app, "GET", "/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=25")
    assert r_parquet.status_code == 200
    payload_p = r_parquet.json()
    assert payload_p["symbol"] == "SOLUSDT"
    assert len(payload_p["candles"]) == 25
    assert payload_p["source"] in {"local_parquet_cache"}

    # An outage must not generate market candles.
    response = _request(app, "GET", "/api/v1/market/klines?symbol=XYZUSDT&interval=15m&limit=20")
    assert response.status_code == 503


def test_market_klines_validation_errors(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    r_bad_interval = _request(app, "GET", "/api/v1/market/klines?interval=99m")
    assert r_bad_interval.status_code == 422
    r_bad_limit = _request(app, "GET", "/api/v1/market/klines?limit=5000")
    assert r_bad_limit.status_code == 422
    r_bad_limit_zero = _request(app, "GET", "/api/v1/market/klines?limit=0")
    assert r_bad_limit_zero.status_code == 422


def test_execution_status_endpoint_returns_live_state(tmp_path: Path) -> None:
    import time

    from autonomous_futures.execution.account_evidence import atomic_json

    snapshot = {
        "source": "binance_authenticated_rest",
        "timestamp_ms": int(time.time() * 1000),
        "account": {
            "multiAssetsMargin": "false",
            "totalWalletBalance": "100",
            "availableBalance": "96",
            "totalInitialMargin": "4",
            "totalMarginBalance": "100.04",
            "totalUnrealizedProfit": "0.04",
        },
        "positions": [
            {
                "symbol": "SOLUSDT",
                "positionAmt": "0.04",
                "entryPrice": "99",
                "markPrice": "100",
                "unRealizedProfit": "0.04",
            }
        ],
        "open_orders": [],
    }
    atomic_json(tmp_path / "exchange-account.json", snapshot)
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
        research_dir=tmp_path,
    )
    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is False
    assert payload["status"] == "ACCOUNT_UNRECONCILED"
    assert payload["positions"]["SOLUSDT"]["position_qty"] == 0.04
    assert payload["aggregate_exposure_usdt"] == 4
    assert payload["solvency"]["cash_usdt"] == 100
    assert payload["solvency"]["available_balance_usdt"] == 96
    assert payload["solvency"]["allocated_margin_usdt"] == 4
    assert payload["solvency"]["zero_balance_drift_verified"] is False
    assert payload["solvency"]["starting_equity_usdt"] is None
    assert payload["solvency"]["drift_usdt"] is None
    assert payload["daily_risk"]["verified"] is False
    assert payload["daily_risk"]["loss_usdt"] is None
    assert payload["intra_day_loss_usdt"] is None


def test_execution_status_uses_wallet_identity_and_verified_dynamic_daily_risk(
    tmp_path: Path,
) -> None:
    import time

    from autonomous_futures.execution.account_evidence import atomic_json

    timestamp_ms = int(time.time() * 1000)
    snapshot = {
        "source": "binance_authenticated_rest",
        "timestamp_ms": timestamp_ms,
        "account": {
            "multiAssetsMargin": "false",
            "totalWalletBalance": "98",
            "availableBalance": "70",
            "totalInitialMargin": "28",
            "totalMarginBalance": "97",
            "totalUnrealizedProfit": "-1",
        },
        "positions": [],
        "open_orders": [],
        "reconciliation": {
            "starting_equity": "100",
            "net_realized_pnl": "-2",
            "wallet_drift": "0",
            "equity_drift": "0",
            "verified": True,
        },
        "daily_risk": {
            "verified": True,
            "observed_ms": timestamp_ms,
            "equity_basis": "ACCOUNT",
            "day_start_equity": "100",
            "limit_pct": "5",
            "limit_usdt": "5",
            "loss_usdt": "3",
            "remaining_usdt": "2",
            "breached": False,
        },
        "daily_loss_usdt": "99",
    }
    atomic_json(tmp_path / "exchange-account.json", snapshot)
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
        research_dir=tmp_path,
    )

    response = _request(app, "GET", "/api/v1/execution/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["solvency"]["cash_usdt"] == 98
    assert payload["solvency"]["available_balance_usdt"] == 70
    assert payload["solvency"]["allocated_margin_usdt"] == 28
    assert payload["solvency"]["total_equity_usdt"] == 97
    assert payload["solvency"]["zero_balance_drift_verified"] is True
    assert payload["daily_risk"] == {
        "verified": True,
        "day_start_equity_usdt": 100,
        "limit_pct": 5,
        "limit_usdt": 5,
        "loss_usdt": 3,
        "remaining_usdt": 2,
        "breached": False,
        "equity_basis": "ACCOUNT",
    }
    assert payload["intra_day_loss_usdt"] == 3


def test_execution_status_fallback_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_research = tmp_path / "empty_research"
    empty_research.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AFBOT_RESEARCH_DIR", str(empty_research))

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
        research_dir=empty_research,
    )
    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 503
    assert "account evidence unavailable" in response.json()["detail"]


def test_execution_status_prefers_freshest_qualified_testnet_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    from decimal import Decimal
    from importlib import import_module

    from autonomous_futures.execution.account_evidence import atomic_json
    from autonomous_futures.strategy.macro_liquidity_scalper import Candle

    def scanner_bars(
        _symbol: str,
        interval: str,
        limit: int,
        _research_dir: Path | None = None,
    ) -> tuple[list[Candle], str]:
        interval_ms = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[interval]
        bars = []
        for index in range(limit):
            close = Decimal("100") + Decimal(index) / Decimal("100")
            bars.append(
                Candle(
                    timestamp_ms=index * interval_ms,
                    open=close,
                    high=close + Decimal("1"),
                    low=close - Decimal("1"),
                    close=close,
                    volume=Decimal(10 + index % 5),
                )
            )
        return bars, "test_fixture"

    api_module = import_module("autonomous_futures.api.app")
    monkeypatch.setattr(api_module, "_load_ohlcv_bars_for_scanner", scanner_bars)

    research_dir = tmp_path / "artifacts" / "research"
    phase310_dir = research_dir / "phase310"
    qualified_dir = tmp_path / "runtime" / "qualified-testnet"
    phase310_dir.mkdir(parents=True, exist_ok=True)
    qualified_dir.mkdir(parents=True, exist_ok=True)

    now_ms = int(time.time() * 1000)
    stale_snapshot = {
        "source": "binance_authenticated_rest",
        "timestamp_ms": now_ms - 60_000,
        "account": {
            "multiAssetsMargin": "false",
            "totalWalletBalance": "100",
            "totalInitialMargin": "0",
            "totalMarginBalance": "100",
            "availableBalance": "100",
            "totalUnrealizedProfit": "0",
        },
        "positions": [],
        "open_orders": [],
    }
    fresh_snapshot = {
        "source": "binance_authenticated_rest",
        "timestamp_ms": now_ms,
        "account": {
            "multiAssetsMargin": "false",
            "totalWalletBalance": "4224.09882354",
            "totalInitialMargin": "0",
            "totalMarginBalance": "4224.09882354",
            "availableBalance": "4224.09882354",
            "totalUnrealizedProfit": "0",
        },
        "positions": [],
        "open_orders": [],
        "reconciliation": {
            "starting_equity": "4224.09882354",
            "net_realized_pnl": "0",
            "net_external_flows": "0",
            "wallet_drift": "0",
            "equity_drift": "0",
            "verified": True,
        },
        "daily_risk": {
            "verified": True,
            "observed_ms": now_ms,
            "equity_basis": "ACCOUNT",
            "day_start_equity": "4224.09882354",
            "limit_pct": "5",
            "limit_usdt": "211.204941177",
            "loss_usdt": "0",
            "remaining_usdt": "211.204941177",
            "breached": False,
        },
    }
    runtime_health = {
        "source": "runtime_observation",
        "timestamp_ms": now_ms,
        "last_protective_cycle_ms": now_ms - 100,
        "cycle_error_type": None,
        "last_account_refresh_error_type": None,
        "scan_error_type": None,
        "market_connected": True,
        "market_error_type": None,
        "user_stream_connected": True,
        "user_stream_reconciliation_required": False,
        "user_stream_entry_block_reason": None,
        "user_stream_error_type": None,
        "user_stream_last_event_type": None,
        "user_stream_event_count": 0,
        "user_stream_gap": False,
        "user_data_event_counts": {},
        "force_flatten_reason": None,
        "market_generation": 2,
        "microstructure": {
            "calibration_window_ms": 1800000,
            "calibration": {
                "beta_per_second": 7.5,
                "artifact_sha256": "a" * 64,
                "trace_sha256s": ["b" * 64],
            },
            "arrival_count": 36930,
            "fit_error": None,
            "fit": {
                "first_ms": now_ms - 1800000,
                "last_ms": now_ms - 10,
                "event_counts": {"BTCUSDT": 4451, "ETHUSDT": 4228, "SOLUSDT": 3147},
                "beta_per_second": 7.5,
                "baseline_boundary_symbols": [],
                "spectral_radius": 0.5455993315954724,
                "arrivals_sha256": "c" * 64,
            },
        },
    }
    atomic_json(phase310_dir / "exchange-account.json", stale_snapshot)
    atomic_json(qualified_dir / "exchange-account.json", fresh_snapshot)
    atomic_json(qualified_dir / "runtime-health.json", runtime_health)

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
        research_dir=research_dir,
    )
    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["solvency"]["total_equity_usdt"] == pytest.approx(4224.09882354)
    assert payload["daily_risk"]["verified"] is True
    assert payload["daily_risk"]["remaining_usdt"] == pytest.approx(211.204941177)
    assert payload["engine_state"] == "QUALIFIED_PORTFOLIO_ACTIVE"
    assert payload["interlock_blocks_count"] == 0
    assert payload["runtime_health"]["observed"] is True
    assert payload["runtime_health"]["market_connected"] is True
    assert payload["runtime_health"]["user_stream_connected"] is True
    assert payload["runtime_health"]["arrival_count"] == 36930
    assert payload["runtime_health"]["spectral_radius"] == pytest.approx(0.5455993315954724)
    assert payload["runtime_health"]["event_counts"]["BTCUSDT"] == 4451
    expected_members = [
        "avax-1-hf-d-3.5-tp6.0-sl10.0",
        "eth-1-deep-d-4.0-tp10.0-sl6.0",
        "eth-2-med-d-3.5-tp10.0-sl8.0",
        "eth-3-hf-d-3.0-tp12.0-sl12.0",
        "sol-1-deep-d-4.0-tp3.0-sl3.0",
        "sol-2-hf-d-1.8-tp8.0-sl10.0",
    ]
    assert payload["scalper_criteria"] is not None
    assert payload["scalper_criteria"]["variant_id"] in set(expected_members)
    assert payload["portfolio_scanner"]["observed"] is True
    assert (
        payload["portfolio_scanner"]["portfolio_id"]
        == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    )
    assert payload["portfolio_scanner"]["ema50_1h"] is not None
    assert payload["portfolio_scanner"]["ema200_1h"] is not None
    assert payload["portfolio_scanner"]["ema50_4h"] is not None
    assert payload["portfolio_scanner"]["ema200_4h"] is not None
    assert [v["member_id"] for v in payload["portfolio_scanner"]["variants"]] == expected_members
    assert (qualified_dir / "portfolio-scanner-state.json").is_file()
    assert payload["watchdog"]["status"] == "HEALTHY"
    assert payload["watchdog"]["healthy"] is True
    assert payload["watchdog"]["critical_alerts"] == []
    assert payload["watchdog"]["warning_alerts"] == []

    wd_resp = _request(app, "GET", "/api/v1/execution/watchdog")
    assert wd_resp.status_code == 200
    wd_payload = wd_resp.json()
    assert wd_payload["schema"] == "qualified-runtime-watchdog-v1"
    assert wd_payload["status"] == "HEALTHY"
    assert wd_payload["healthy"] is True
    assert wd_payload["checks"]["account_reconciliation"]["passed"] is True
    assert wd_payload["checks"]["daily_risk_budget"]["passed"] is True
    assert wd_payload["checks"]["streams_and_hawkes"]["passed"] is True
    assert wd_payload["checks"]["portfolio_scanner"]["passed"] is True

    # Verify reading a fresh qualified_runtime_scanner state file directly
    import json

    runtime_state_file = json.loads(
        (qualified_dir / "portfolio-scanner-state.json").read_text(encoding="utf-8")
    )
    runtime_state_file["source"] = "qualified_runtime_scanner"
    runtime_state_file["evaluated_at_ms"] = now_ms
    atomic_json(qualified_dir / "portfolio-scanner-state.json", runtime_state_file)
    from_scanner_payload = _request(app, "GET", "/api/v1/execution/status").json()
    assert from_scanner_payload["portfolio_scanner"]["source"] == "qualified_runtime_scanner"
    assert [
        v["member_id"] for v in from_scanner_payload["portfolio_scanner"]["variants"]
    ] == expected_members

    warmup_health = {
        **runtime_health,
        "microstructure": {
            "calibration_window_ms": 1800000,
            "arrival_count": 6307,
            "fit_error": (
                "Every model dimension needs at least 390 observed arrivals "
                "for 13 fitted coefficients"
            ),
            "fit": None,
        },
    }
    atomic_json(qualified_dir / "runtime-health.json", warmup_health)
    warmup_payload = _request(app, "GET", "/api/v1/execution/status").json()
    assert warmup_payload["engine_state"] == "QUALIFIED_PORTFOLIO_WARMUP"
    assert warmup_payload["watchdog"]["status"] == "WARNING"
    assert "hawkes_microstructure_warmup" in warmup_payload["watchdog"]["warning_alerts"]
