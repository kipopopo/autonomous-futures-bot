from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)

START = datetime(2026, 8, 7, tzinfo=UTC)
END = START + timedelta(hours=1)
OBSERVED = datetime(2026, 8, 7, 12, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry(
    kind: str,
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
