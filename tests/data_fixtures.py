from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from autonomous_futures.api.catalog import VerifiedDatasetCatalog
from autonomous_futures.data.builder import KlineInterval
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
from autonomous_futures.data.parquet import read_canonical_parquet, write_canonical_parquet
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)


def write_primary_cached_catalog(parquet: Path, root: Path) -> VerifiedDatasetCatalog:
    """Build a complete, explicitly synthetic catalog around a cached test kline file."""
    frame = read_canonical_parquet(parquet, interval=timedelta(minutes=5))
    start = frame["timestamp"].iloc[0].to_pydatetime()
    last = frame["timestamp"].iloc[-1].to_pydatetime()
    end = last + timedelta(minutes=5)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    symbol = "BTCUSDT"

    def kline_entry(
        *,
        interval: KlineInterval,
        path: Path,
        bars: pd.DataFrame,
        time_start: datetime,
        time_end: datetime,
    ) -> DatasetRegistryEntry:
        manifest_ref = f"manifests/{symbol}-{interval}.json"
        manifest = build_manifest(
            symbols=(symbol,),
            source_files=(
                describe_data_file(
                    path,
                    relative_path=path.relative_to(root).as_posix(),
                    rows=len(bars),
                ),
            ),
            time_start=time_start,
            time_end=time_end,
            created_at=now,
            code_version="cached-cycle-test-fixture",
            dependency_lock_hash="test-only",
            dataset_interval=interval,
        )
        write_manifest(root / manifest_ref, manifest)
        return DatasetRegistryEntry(
            kind="kline",
            symbols=(symbol,),
            interval=interval,
            time_start=time_start,
            time_end=time_end,
            observed_at=now,
            schema_version=f"kline-{interval}-v1",
            content_hash=manifest.manifest_hash,
            artifact_ref=manifest_ref,
            endpoint_path="/fapi/v1/klines",
            provenance=("unsigned", "cached_test_fixture"),
        )

    primary_entry = kline_entry(
        interval="5m", path=parquet, bars=frame, time_start=start, time_end=last
    )

    context_start = pd.Timestamp(start).floor("15min") - pd.Timedelta(minutes=15)
    context_end = pd.Timestamp(last).floor("15min")
    context_times = pd.date_range(context_start, context_end, freq="15min")
    source_times = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    context_rows = []
    for timestamp in context_times:
        position = int(source_times.searchsorted(timestamp, side="right")) - 1
        source = frame.iloc[max(position, 0)]
        context_rows.append(
            {
                "timestamp": timestamp,
                "open": source["open"],
                "high": source["high"],
                "low": source["low"],
                "close": source["close"],
            }
        )
    context_frame = pd.DataFrame(context_rows)
    context_path = root / "15m/canonical/BTCUSDT-15m.parquet"
    context_frame = write_canonical_parquet(
        context_frame, context_path, interval=timedelta(minutes=15)
    )
    context_entry = kline_entry(
        interval="15m",
        path=context_path,
        bars=context_frame,
        time_start=context_frame["timestamp"].iloc[0].to_pydatetime(),
        time_end=context_frame["timestamp"].iloc[-1].to_pydatetime(),
    )

    mark_ref = "canonical/BTCUSDT-mark.parquet"
    mark_manifest_ref = "manifests/BTCUSDT-mark.json"
    mark_frame = pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": pd.to_datetime(frame["timestamp"], utc=True),
            "open": frame["open"],
            "high": frame["high"],
            "low": frame["low"],
            "close": frame["close"],
            "close_time": pd.to_datetime(frame["timestamp"], utc=True)
            + pd.Timedelta(minutes=5)
            - pd.Timedelta(milliseconds=1),
        }
    )
    mark_manifest = write_mark_price_artifact(
        mark_frame,
        root / mark_ref,
        root / mark_manifest_ref,
        artifact_ref=mark_ref,
        symbol=symbol,
        interval="5m",
        time_start=start,
        time_end=end,
        created_at=now,
        code_version="cached-cycle-test-fixture",
        dependency_lock_hash="test-only",
    )
    mark_entry = DatasetRegistryEntry(
        kind="mark_price",
        symbols=(symbol,),
        interval="5m",
        time_start=start,
        time_end=end,
        observed_at=now,
        schema_version="mark_price-v1",
        content_hash=mark_manifest.manifest_hash,
        artifact_ref=mark_manifest_ref,
        endpoint_path="/fapi/v1/markPriceKlines",
        provenance=("unsigned", "cached_test_fixture"),
    )

    funding_ref = "canonical/BTCUSDT-funding.parquet"
    funding_manifest_ref = "manifests/BTCUSDT-funding.json"
    funding_start = start - timedelta(hours=8)
    funding_end = end + timedelta(hours=8)
    event_times = (
        max(start + timedelta(minutes=1), end - timedelta(minutes=10)),
        max(start + timedelta(minutes=2), end - timedelta(minutes=5)),
    )
    funding_frame = pd.DataFrame(
        {
            "symbol": [symbol, symbol],
            "funding_time": [pd.Timestamp(event_time) for event_time in event_times],
            "funding_rate": [Decimal("0.0001"), Decimal("-0.0002")],
            "funding_mark_price": [Decimal("60000"), Decimal("60100")],
        }
    )
    funding_manifest = write_funding_artifact(
        funding_frame,
        root / funding_ref,
        root / funding_manifest_ref,
        artifact_ref=funding_ref,
        symbol=symbol,
        time_start=funding_start,
        time_end=funding_end,
        created_at=now,
        code_version="cached-cycle-test-fixture",
        dependency_lock_hash="test-only",
    )
    funding_entry = DatasetRegistryEntry(
        kind="funding_rate",
        symbols=(symbol,),
        interval=None,
        time_start=funding_start,
        time_end=funding_end,
        observed_at=now,
        schema_version="funding_rate-v1",
        content_hash=funding_manifest.manifest_hash,
        artifact_ref=funding_manifest_ref,
        endpoint_path="/fapi/v1/fundingRate",
        provenance=("unsigned", "cached_test_fixture"),
    )

    filters_ref = "metadata/exchange-filters.json"
    filters = build_exchange_filter_snapshot(
        {
            "symbols": [
                {
                    "symbol": symbol,
                    "pair": symbol,
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
        },
        symbols=(symbol,),
        observed_at=now,
    )
    write_exchange_filter_snapshot(root / filters_ref, filters)
    filters_entry = DatasetRegistryEntry(
        kind="exchange_filters",
        symbols=(symbol,),
        interval=None,
        time_start=None,
        time_end=None,
        observed_at=now,
        schema_version="exchange_filters-v1",
        content_hash=filters.snapshot_hash,
        artifact_ref=filters_ref,
        endpoint_path="/fapi/v1/exchangeInfo",
        provenance=("unsigned", "cached_test_fixture"),
    )

    entries = (primary_entry, context_entry, mark_entry, funding_entry, filters_entry)
    registry = build_dataset_registry(entries, created_at=now)
    bundle = build_dataset_bundle(
        registry, symbols=("BTCUSDT",), time_start=start, time_end=end, created_at=now
    )
    write_dataset_registry(root / "registry.json", registry)
    write_dataset_bundle(root / "bundle.json", bundle)
    return VerifiedDatasetCatalog(bundle=bundle, registry=registry)
