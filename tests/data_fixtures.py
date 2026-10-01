from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from autonomous_futures.api.catalog import VerifiedDatasetCatalog
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.manifest import build_manifest, describe_data_file, write_manifest
from autonomous_futures.data.parquet import read_canonical_parquet
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
)


def write_primary_cached_catalog(parquet: Path, root: Path) -> VerifiedDatasetCatalog:
    """Hash-bind a test Parquet; non-primary entries remain unavailable test-only coverage."""
    frame = read_canonical_parquet(parquet, interval=timedelta(minutes=5))
    start = frame["timestamp"].iloc[0].to_pydatetime()
    last = frame["timestamp"].iloc[-1].to_pydatetime()
    end = last + timedelta(minutes=5)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    manifest = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(
            describe_data_file(
                parquet, relative_path=parquet.relative_to(root).as_posix(), rows=len(frame)
            ),
        ),
        time_start=start,
        time_end=last,
        created_at=now,
        code_version="cached-cycle-test-fixture",
        dependency_lock_hash="test-only",
    )
    write_manifest(root / "manifest.json", manifest)
    entries = tuple(
        DatasetRegistryEntry(
            kind=kind,
            symbols=("BTCUSDT",),
            interval=interval,
            time_start=lower,
            time_end=upper,
            observed_at=now,
            schema_version="cached-cycle-fixture-v1",
            content_hash=content_hash,
            artifact_ref=ref,
            endpoint_path=endpoint,
            provenance=("unsigned", "cached_test_fixture"),
        )
        for kind, interval, lower, upper, content_hash, ref, endpoint in (
            (
                "kline",
                "5m",
                start,
                last,
                manifest.manifest_hash,
                "manifest.json",
                "/fapi/v1/klines",
            ),
            (
                "kline",
                "15m",
                start - timedelta(minutes=15),
                end,
                "1" * 64,
                "unavailable-context.json",
                "/fapi/v1/klines",
            ),
            (
                "mark_price",
                "5m",
                start,
                end,
                "2" * 64,
                "unavailable-mark.json",
                "/fapi/v1/markPriceKlines",
            ),
            (
                "funding_rate",
                None,
                start - timedelta(hours=8),
                end,
                "3" * 64,
                "unavailable-funding.json",
                "/fapi/v1/fundingRate",
            ),
            (
                "exchange_filters",
                None,
                None,
                None,
                "4" * 64,
                "unavailable-filters.json",
                "/fapi/v1/exchangeInfo",
            ),
        )
    )
    registry = build_dataset_registry(entries, created_at=now)
    bundle = build_dataset_bundle(
        registry, symbols=("BTCUSDT",), time_start=start, time_end=end, created_at=now
    )
    write_dataset_registry(root / "registry.json", registry)
    write_dataset_bundle(root / "bundle.json", bundle)
    return VerifiedDatasetCatalog(bundle=bundle, registry=registry)
