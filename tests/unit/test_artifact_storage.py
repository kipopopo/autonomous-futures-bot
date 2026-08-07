from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd
import pytest

from autonomous_futures.api.artifacts import (
    ArtifactIntegrityError,
    inspect_artifact_entry,
)
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.derivatives_artifacts import write_funding_artifact
from autonomous_futures.data.exchange_filters import (
    build_exchange_filter_snapshot,
    write_exchange_filter_snapshot,
)
from autonomous_futures.data.manifest import build_manifest, describe_data_file, write_manifest
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)

START = datetime(2026, 8, 7, tzinfo=UTC)
END = START + timedelta(minutes=10)
OBSERVED = datetime(2026, 8, 7, 12, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry(
    kind: str,
    *,
    interval: str | None,
    time_start: datetime | None,
    time_end: datetime | None,
    content_hash: str,
    artifact_ref: str,
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
        artifact_ref=artifact_ref,
        endpoint_path=endpoints[kind],
        provenance=("binance_public_rest", "unsigned", "api_fixture"),
    )


def test_inspects_kline_manifest_and_all_source_file_hashes(tmp_path: Path) -> None:
    artifact_dir = tmp_path / SYMBOL
    raw_path = artifact_dir / "raw" / "BTCUSDT-5m.csv"
    canonical_path = artifact_dir / "canonical" / "BTCUSDT-5m.parquet"
    manifest_path = artifact_dir / "manifests" / "BTCUSDT-5m.manifest.json"
    raw_path.parent.mkdir(parents=True)
    canonical_path.parent.mkdir(parents=True)
    raw_path.write_text("raw fixture\n", encoding="utf-8")
    canonical_path.write_bytes(b"canonical fixture")

    manifest = build_manifest(
        symbols=(SYMBOL,),
        source_files=(
            describe_data_file(raw_path, relative_path="raw/BTCUSDT-5m.csv", rows=1),
            describe_data_file(
                canonical_path,
                relative_path="canonical/BTCUSDT-5m.parquet",
                rows=1,
            ),
        ),
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
        code_version="test",
        dependency_lock_hash="uv.lock",
        dataset_interval="5m",
    )
    write_manifest(manifest_path, manifest)
    entry = _entry(
        "kline",
        interval="5m",
        time_start=START,
        time_end=END,
        content_hash=manifest.manifest_hash,
        artifact_ref=f"{SYMBOL}/manifests/{manifest_path.name}",
    )

    inspection = inspect_artifact_entry(tmp_path, entry)

    assert inspection.verified is True
    assert inspection.manifest_hash == manifest.manifest_hash
    assert inspection.source_file_count == 2


def test_inspects_funding_manifest_and_parquet_hash(tmp_path: Path) -> None:
    artifact_path = tmp_path / SYMBOL / "canonical" / "BTCUSDT-funding.parquet"
    manifest_path = tmp_path / SYMBOL / "manifests" / "BTCUSDT-funding.json"
    funding_frame = pd.DataFrame(
        {
            "symbol": [SYMBOL],
            "funding_time": pd.to_datetime([START], utc=True),
            "funding_rate": [Decimal("0.00010000")],
            "funding_mark_price": [Decimal("100")],
        }
    )
    manifest = write_funding_artifact(
        funding_frame,
        artifact_path,
        manifest_path,
        artifact_ref=f"{SYMBOL}/canonical/{artifact_path.name}",
        symbol=SYMBOL,
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
        code_version="test",
        dependency_lock_hash="uv.lock",
    )
    entry = _entry(
        "funding_rate",
        interval=None,
        time_start=START,
        time_end=END,
        content_hash=manifest.manifest_hash,
        artifact_ref=f"{SYMBOL}/manifests/{manifest_path.name}",
    )

    inspection = inspect_artifact_entry(tmp_path, entry)

    assert inspection.verified is True
    assert inspection.artifact_sha256 == manifest.artifact_sha256
    assert inspection.rows == 1


def test_inspects_exchange_filter_snapshot_hash(tmp_path: Path) -> None:
    artifact_path = tmp_path / SYMBOL / "filters" / "exchange-filters.json"
    snapshot = build_exchange_filter_snapshot(
        {
            "symbols": [
                {
                    "symbol": SYMBOL,
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "filters": [
                        {
                            "filterType": "PRICE_FILTER",
                            "minPrice": "0.10",
                            "maxPrice": "1000000",
                            "tickSize": "0.10",
                        },
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "1000",
                            "stepSize": "0.001",
                        },
                        {
                            "filterType": "MARKET_LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "1000",
                            "stepSize": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": "50"},
                    ],
                }
            ]
        },
        symbols=(SYMBOL,),
        observed_at=OBSERVED,
    )
    write_exchange_filter_snapshot(artifact_path, snapshot)
    entry = _entry(
        "exchange_filters",
        interval=None,
        time_start=None,
        time_end=None,
        content_hash=snapshot.snapshot_hash,
        artifact_ref=f"{SYMBOL}/filters/{artifact_path.name}",
    )

    inspection = inspect_artifact_entry(tmp_path, entry)

    assert inspection.verified is True
    assert inspection.manifest_hash == snapshot.snapshot_hash
    assert inspection.source_file_count == 1


def test_artifact_verification_fails_closed_on_missing_or_tampered_file(
    tmp_path: Path,
) -> None:
    entry = _entry(
        "exchange_filters",
        interval=None,
        time_start=None,
        time_end=None,
        content_hash="1" * 64,
        artifact_ref="BTCUSDT/filters/missing.json",
    )

    with pytest.raises(ArtifactIntegrityError, match="does not exist"):
        inspect_artifact_entry(tmp_path, entry)


def test_components_endpoint_fails_closed_when_artifact_root_is_incomplete(tmp_path: Path) -> None:
    from autonomous_futures.api import create_app

    entries = tuple(
        _entry(
            kind,
            interval=interval,
            time_start=time_start,
            time_end=time_end,
            content_hash=content_hash,
            artifact_ref=f"{SYMBOL}/missing/{kind}.json",
        )
        for kind, interval, time_start, time_end, content_hash in (
            ("kline", "5m", START, END - timedelta(minutes=5), "1" * 64),
            (
                "kline",
                "15m",
                START - timedelta(minutes=15),
                END - timedelta(minutes=15),
                "2" * 64,
            ),
            ("mark_price", "5m", START, END, "3" * 64),
            ("funding_rate", None, START - timedelta(hours=8), END, "4" * 64),
            ("exchange_filters", None, None, None, "5" * 64),
        )
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

    app = create_app(
        bundle_path=bundle_path,
        registry_path=registry_path,
        artifact_root=tmp_path,
    )

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/dataset/components")

    response = asyncio.run(send())

    assert response.status_code == 503
    assert response.json() == {"detail": "dataset artifact integrity verification failed"}
