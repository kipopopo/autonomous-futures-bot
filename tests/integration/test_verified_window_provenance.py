from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.derivatives_artifacts import (
    write_funding_artifact,
    write_mark_price_artifact,
)
from autonomous_futures.data.exchange_filters import (
    build_exchange_filter_snapshot,
    write_exchange_filter_snapshot,
)
from autonomous_futures.data.manifest import build_manifest, describe_data_file, write_manifest
from autonomous_futures.data.parquet import write_canonical_parquet
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)

START = datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
END = START + timedelta(minutes=150)
OBSERVED = START + timedelta(days=1)
SYMBOL = "BTCUSDT"


def _entry(
    kind: str,
    *,
    interval: str | None,
    time_start: datetime | None,
    time_end: datetime | None,
    artifact_ref: str,
    content_hash: str,
) -> DatasetRegistryEntry:
    endpoint = {
        "kline": "/fapi/v1/klines",
        "funding_rate": "/fapi/v1/fundingRate",
        "mark_price": "/fapi/v1/markPriceKlines",
        "exchange_filters": "/fapi/v1/exchangeInfo",
    }[kind]
    symbols = (SYMBOL,)
    return DatasetRegistryEntry(
        kind=kind,
        symbols=symbols,
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        observed_at=OBSERVED,
        schema_version=f"{kind}-v1",
        content_hash=content_hash,
        artifact_ref=artifact_ref,
        endpoint_path=endpoint,
        provenance=("binance_public_rest", "unsigned", "integration_fixture"),
    )


def _write_kline(
    root: Path,
    *,
    interval: str,
    start: datetime,
    timestamps: tuple[datetime, ...],
) -> DatasetRegistryEntry:
    minutes = 5 if interval == "5m" else 15
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal("100") + index for index, _ in enumerate(timestamps)],
            "high": [Decimal("101") + index for index, _ in enumerate(timestamps)],
            "low": [Decimal("99") + index for index, _ in enumerate(timestamps)],
            "close": [Decimal("100") + index for index, _ in enumerate(timestamps)],
        }
    )
    parquet_ref = f"canonical/{SYMBOL}-{interval}.parquet"
    parquet_path = root / parquet_ref
    write_canonical_parquet(frame, parquet_path, interval=timedelta(minutes=minutes))
    manifest_ref = f"manifests/{SYMBOL}-{interval}.json"
    manifest_path = root / manifest_ref
    manifest = build_manifest(
        symbols=(SYMBOL,),
        source_files=(
            describe_data_file(
                parquet_path,
                relative_path=parquet_ref,
                rows=len(frame),
            ),
        ),
        time_start=start,
        time_end=timestamps[-1],
        created_at=OBSERVED,
        code_version="synthetic-integration-fixture",
        dependency_lock_hash="test-lock-hash",
        dataset_interval=interval,
    )
    write_manifest(manifest_path, manifest)
    return _entry(
        "kline",
        interval=interval,
        time_start=start,
        time_end=timestamps[-1],
        artifact_ref=manifest_ref,
        content_hash=manifest.manifest_hash,
    )


def _exchange_payload() -> dict[str, object]:
    return {
        "symbols": [
            {
                "symbol": SYMBOL,
                "pair": SYMBOL,
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
            }
        ]
    }


def _write_complete_catalog(root: Path) -> tuple[Path, Path, Path, str, str]:
    timestamps_5m = tuple(START + timedelta(minutes=5 * index) for index in range(30))
    primary = _write_kline(root, interval="5m", start=START, timestamps=timestamps_5m)
    context = _write_kline(
        root,
        interval="15m",
        start=START - timedelta(minutes=15),
        timestamps=tuple(
            START - timedelta(minutes=15) + timedelta(minutes=15 * index) for index in range(11)
        ),
    )

    mark_ref = "canonical/BTCUSDT-mark.parquet"
    mark_manifest_ref = "manifests/BTCUSDT-mark.json"
    mark_frame = pd.DataFrame(
        {
            "symbol": [SYMBOL] * len(timestamps_5m),
            "timestamp": [pd.Timestamp(value) for value in timestamps_5m],
            "open": [Decimal("100")] * len(timestamps_5m),
            "high": [Decimal("101")] * len(timestamps_5m),
            "low": [Decimal("99")] * len(timestamps_5m),
            "close": [Decimal("100")] * len(timestamps_5m),
            "close_time": [
                pd.Timestamp(value + timedelta(minutes=5) - timedelta(milliseconds=1))
                for value in timestamps_5m
            ],
        }
    )
    mark_manifest = write_mark_price_artifact(
        mark_frame,
        root / mark_ref,
        root / mark_manifest_ref,
        artifact_ref=mark_ref,
        symbol=SYMBOL,
        interval="5m",
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
        code_version="synthetic-integration-fixture",
        dependency_lock_hash="test-lock-hash",
    )
    mark_entry = _entry(
        "mark_price",
        interval="5m",
        time_start=START,
        time_end=END,
        artifact_ref=mark_manifest_ref,
        content_hash=mark_manifest.manifest_hash,
    )

    funding_ref = "canonical/BTCUSDT-funding.parquet"
    funding_manifest_ref = "manifests/BTCUSDT-funding.json"
    funding_start = START - timedelta(hours=8)
    funding_end = END + timedelta(hours=8)
    funding_frame = pd.DataFrame(
        {
            "symbol": [SYMBOL, SYMBOL],
            "funding_time": [
                pd.Timestamp(END - timedelta(minutes=10)),
                pd.Timestamp(END - timedelta(minutes=5)),
            ],
            "funding_rate": [Decimal("0.0001"), Decimal("-0.0002")],
            "funding_mark_price": [Decimal("60000"), Decimal("60100")],
        }
    )
    funding_manifest = write_funding_artifact(
        funding_frame,
        root / funding_ref,
        root / funding_manifest_ref,
        artifact_ref=funding_ref,
        symbol=SYMBOL,
        time_start=funding_start,
        time_end=funding_end,
        created_at=OBSERVED,
        code_version="synthetic-integration-fixture",
        dependency_lock_hash="test-lock-hash",
    )
    funding_entry = _entry(
        "funding_rate",
        interval=None,
        time_start=funding_start,
        time_end=funding_end,
        artifact_ref=funding_manifest_ref,
        content_hash=funding_manifest.manifest_hash,
    )

    filters_ref = "metadata/exchange-filters.json"
    filters = build_exchange_filter_snapshot(
        _exchange_payload(), symbols=(SYMBOL,), observed_at=OBSERVED
    )
    write_exchange_filter_snapshot(root / filters_ref, filters)
    filters_entry = _entry(
        "exchange_filters",
        interval=None,
        time_start=None,
        time_end=None,
        artifact_ref=filters_ref,
        content_hash=filters.snapshot_hash,
    )

    registry = build_dataset_registry(
        (primary, context, mark_entry, funding_entry, filters_entry),
        created_at=OBSERVED,
    )
    registry_path = root / "registry.json"
    write_dataset_registry(registry_path, registry)
    bundle = build_dataset_bundle(
        registry,
        symbols=(SYMBOL,),
        time_start=START,
        time_end=END,
        created_at=OBSERVED,
    )
    bundle_path = root / "bundle.json"
    write_dataset_bundle(bundle_path, bundle)
    return root, bundle_path, registry_path, bundle.bundle_hash, registry.registry_hash


def test_real_bundle_to_cached_window_binds_kline_and_funding_bytes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.evaluate_phase_250_walk_forward import load_verified_oos_windows
    from scripts.explore_offline_strategies import (
        load_and_slice_windows as load_exploration_windows,
    )
    from scripts.run_autonomous_cycle import load_and_slice_windows

    root, bundle_path, registry_path, bundle_hash, registry_hash = _write_complete_catalog(
        tmp_path / "dataset"
    )
    parquet_path = root / f"canonical/{SYMBOL}-5m.parquet"
    windows = load_and_slice_windows(
        parquet_path,
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        windows_count=1,
        bars_per_window=3,
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    window = windows[0]

    assert window.spec.bundle_hash == bundle_hash
    assert window.spec.dataset_registry_hash == registry_hash
    assert window.spec.funding_artifact_hash is not None
    assert window.funding_slice is not None
    assert window.funding_slice.bundle_hash == bundle_hash
    assert window.funding_slice.dataset_registry_hash == registry_hash
    assert tuple(window.copy_funding_events()["funding_time"]) == (
        pd.Timestamp(END - timedelta(minutes=10)),
        pd.Timestamp(END - timedelta(minutes=5)),
    )

    phase250_windows = load_verified_oos_windows(
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        count=1,
        bars_per_window=30,
        start=START,
        data_dir=root / "canonical",
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    assert len(phase250_windows) == 1
    assert phase250_windows[0].frame.shape[0] == 30
    assert phase250_windows[0].funding_slice is not None
    assert phase250_windows[0].spec.funding_artifact_hash is not None

    exploration_windows = load_exploration_windows(
        parquet_path,
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        windows_count=1,
        bars_per_window=30,
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    assert len(exploration_windows) == 1
    assert exploration_windows[0].funding_slice is not None
