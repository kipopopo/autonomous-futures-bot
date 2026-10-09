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


def test_market_prices_endpoint(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/market/prices")
    assert response.status_code == 200
    payload = response.json()
    assert "timestamp_ms" in payload
    assert "prices" in payload
    assert "BTCUSDT" in payload["prices"]
    assert "ETHUSDT" in payload["prices"]
    assert "SOLUSDT" in payload["prices"]
    assert payload["prices"]["BTCUSDT"] > 0
    assert payload["prices"]["ETHUSDT"] > 0
    assert payload["prices"]["SOLUSDT"] > 0
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
    assert payload_p["source"] in {"local_parquet_cache", "synthetic_fallback"}

    # Tier 3: Synthetic fallback for symbol with no local parquet
    r_synth = _request(app, "GET", "/api/v1/market/klines?symbol=XYZUSDT&interval=15m&limit=20")
    assert r_synth.status_code == 200
    payload_s = r_synth.json()
    assert payload_s["symbol"] == "XYZUSDT"
    assert len(payload_s["candles"]) == 20
    assert payload_s["source"] == "synthetic_fallback"


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



