from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.bundle import (
    build_dataset_bundle,
    read_dataset_bundle,
    write_dataset_bundle,
)
from autonomous_futures.data.derivatives_artifacts import (
    FUNDING_PRICE_SOURCE_ENDPOINT,
    FUNDING_PRICE_SOURCE_MARK_OPEN,
    write_funding_artifact,
    write_mark_price_artifact,
)
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    read_dataset_registry,
    write_dataset_registry,
)
from autonomous_futures.data.verified_funding import load_verified_funding_slice
from autonomous_futures.research.cached_evaluation import load_verified_cached_evaluation_window

UTC_START = datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
UTC_END = UTC_START + timedelta(minutes=15)
OBSERVED_AT = UTC_START + timedelta(days=1)
SYMBOL = "BTCUSDT"


def _registry_entry(
    kind: str,
    *,
    interval: str | None,
    time_start: datetime | None,
    time_end: datetime | None,
    artifact_ref: str,
    content_hash: str,
) -> DatasetRegistryEntry:
    endpoints = {
        "kline": "/fapi/v1/klines",
        "funding_rate": "/fapi/v1/fundingRate",
        "mark_price": "/fapi/v1/markPriceKlines",
        "exchange_filters": "/fapi/v1/exchangeInfo",
    }
    return DatasetRegistryEntry(
        kind=kind,
        symbols=(SYMBOL,),
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        observed_at=OBSERVED_AT,
        schema_version=f"{kind}-v1",
        content_hash=content_hash,
        artifact_ref=artifact_ref,
        endpoint_path=endpoints[kind],
        provenance=("binance_public_rest", "unsigned", "synthetic_test_fixture"),
    )


def _verified_catalog(
    tmp_path: Path,
    *,
    fallback_source: bool = False,
    source_hash_override: str | None = None,
    funding_price_override: Decimal | None = None,
) -> tuple[Path, Path, Path, str]:
    artifact_root = tmp_path / "artifacts"
    artifact_path = artifact_root / "canonical" / "funding.parquet"
    manifest_path = artifact_root / "manifests" / "funding.json"
    artifact_start = UTC_START - timedelta(hours=8)
    artifact_end = UTC_END + timedelta(hours=8)
    mark_manifest = None
    if fallback_source:
        mark_frame = pd.DataFrame(
            {
                "symbol": [SYMBOL] * 3,
                "timestamp": pd.date_range(UTC_START, periods=3, freq="5min", tz="UTC"),
                "open": [Decimal("60000"), Decimal("60050"), Decimal("60100")],
                "high": [Decimal("60010"), Decimal("60060"), Decimal("60110")],
                "low": [Decimal("59990"), Decimal("60040"), Decimal("60090")],
                "close": [Decimal("60005"), Decimal("60055"), Decimal("60105")],
                "close_time": pd.date_range(
                    UTC_START + timedelta(minutes=5) - timedelta(milliseconds=1),
                    periods=3,
                    freq="5min",
                    tz="UTC",
                ),
            }
        )
        mark_manifest = write_mark_price_artifact(
            mark_frame,
            artifact_root / "canonical" / "mark.parquet",
            artifact_root / "manifests" / "mark.json",
            artifact_ref="canonical/mark.parquet",
            symbol=SYMBOL,
            interval="5m",
            time_start=UTC_START,
            time_end=UTC_END,
            created_at=OBSERVED_AT,
            code_version="synthetic-test",
            dependency_lock_hash="test-lock-hash",
        )
    funding_frame = pd.DataFrame(
        {
            "symbol": [SYMBOL, SYMBOL, SYMBOL],
            "funding_time": [
                pd.Timestamp(UTC_START),
                pd.Timestamp(UTC_START + timedelta(minutes=10)),
                pd.Timestamp(UTC_END),
            ],
            "funding_rate": [Decimal("0.0001"), Decimal("-0.0002"), Decimal("0.0003")],
            "funding_mark_price": [Decimal("60000"), Decimal("60100"), Decimal("60200")],
        }
    )
    if fallback_source:
        assert mark_manifest is not None
        if funding_price_override is not None:
            funding_frame.loc[1, "funding_mark_price"] = funding_price_override
        funding_frame["funding_mark_price_source"] = [
            FUNDING_PRICE_SOURCE_ENDPOINT,
            FUNDING_PRICE_SOURCE_MARK_OPEN,
            FUNDING_PRICE_SOURCE_ENDPOINT,
        ]
        funding_frame["funding_mark_price_source_artifact_hash"] = [
            None,
            source_hash_override or mark_manifest.manifest_hash,
            None,
        ]
    manifest = write_funding_artifact(
        funding_frame,
        artifact_path,
        manifest_path,
        artifact_ref="canonical/funding.parquet",
        symbol=SYMBOL,
        time_start=artifact_start,
        time_end=artifact_end,
        created_at=OBSERVED_AT,
        code_version="synthetic-test",
        dependency_lock_hash="test-lock-hash",
    )
    entries = (
        _registry_entry(
            "kline",
            interval="5m",
            time_start=UTC_START,
            time_end=UTC_END - timedelta(minutes=5),
            artifact_ref="manifests/5m.json",
            content_hash="1" * 64,
        ),
        _registry_entry(
            "kline",
            interval="15m",
            time_start=UTC_START - timedelta(minutes=15),
            time_end=UTC_START,
            artifact_ref="manifests/15m.json",
            content_hash="2" * 64,
        ),
        _registry_entry(
            "mark_price",
            interval="5m",
            time_start=UTC_START,
            time_end=UTC_END,
            artifact_ref="manifests/mark.json",
            content_hash=mark_manifest.manifest_hash if mark_manifest else "3" * 64,
        ),
        _registry_entry(
            "funding_rate",
            interval=None,
            time_start=artifact_start,
            time_end=artifact_end,
            artifact_ref="manifests/funding.json",
            content_hash=manifest.manifest_hash,
        ),
        _registry_entry(
            "exchange_filters",
            interval=None,
            time_start=None,
            time_end=None,
            artifact_ref="metadata/filters.json",
            content_hash="5" * 64,
        ),
    )
    registry = build_dataset_registry(entries, created_at=OBSERVED_AT)
    registry_path = tmp_path / "dataset-registry.json"
    write_dataset_registry(registry_path, registry)
    bundle = build_dataset_bundle(
        registry,
        symbols=(SYMBOL,),
        time_start=UTC_START,
        time_end=UTC_END,
        created_at=OBSERVED_AT,
    )
    bundle_path = tmp_path / "dataset-bundle.json"
    write_dataset_bundle(bundle_path, bundle)
    return artifact_root, bundle_path, registry_path, manifest.manifest_hash


def test_load_verified_funding_slice_binds_manifest_bytes_catalog_and_range(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, expected_manifest_hash = _verified_catalog(tmp_path)
    bundle = read_dataset_bundle(bundle_path)
    registry = read_dataset_registry(registry_path)

    funding_slice = load_verified_funding_slice(
        artifact_root=artifact_root,
        bundle_path=bundle_path,
        registry_path=registry_path,
        symbol=SYMBOL,
        time_start=UTC_START,
        time_end=UTC_END,
        bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
        expected_bundle_hash=bundle.bundle_hash,
        expected_registry_hash=registry.registry_hash,
    )

    assert funding_slice.bundle_hash == bundle.bundle_hash
    assert funding_slice.dataset_registry_hash == registry.registry_hash
    assert funding_slice.manifest_hash == expected_manifest_hash
    assert funding_slice.symbol == SYMBOL
    assert funding_slice.time_start == UTC_START
    assert funding_slice.time_end == UTC_END
    assert tuple(funding_slice.copy_events()["funding_time"]) == (
        pd.Timestamp(UTC_START),
        pd.Timestamp(UTC_START + timedelta(minutes=10)),
    )


def test_load_verified_funding_slice_checks_fallback_against_exact_mark_open(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(
        tmp_path,
        fallback_source=True,
    )

    funding_slice = load_verified_funding_slice(
        artifact_root=artifact_root,
        bundle_path=bundle_path,
        registry_path=registry_path,
        symbol=SYMBOL,
        time_start=UTC_START,
        time_end=UTC_END,
        bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
    )

    events = funding_slice.copy_events()
    assert events["funding_mark_price"].tolist() == [
        Decimal("60000"),
        Decimal("60100"),
    ]
    assert events["funding_mark_price_source"].tolist() == [
        FUNDING_PRICE_SOURCE_ENDPOINT,
        FUNDING_PRICE_SOURCE_MARK_OPEN,
    ]
    source_hashes = events["funding_mark_price_source_artifact_hash"].tolist()
    mark_hash = next(
        entry.content_hash
        for entry in read_dataset_registry(registry_path).entries
        if entry.kind == "mark_price"
    )
    assert source_hashes[0] is None
    assert source_hashes[1] == mark_hash


def test_load_verified_funding_slice_rejects_unbound_fallback_source_hash(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(
        tmp_path,
        fallback_source=True,
        source_hash_override="9" * 64,
    )

    with pytest.raises(DataQualityError, match="fallback provenance"):
        load_verified_funding_slice(
            artifact_root=artifact_root,
            bundle_path=bundle_path,
            registry_path=registry_path,
            symbol=SYMBOL,
            time_start=UTC_START,
            time_end=UTC_END,
            bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
        )


def test_load_verified_funding_slice_rejects_fallback_value_not_matching_mark_open(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(
        tmp_path,
        fallback_source=True,
        funding_price_override=Decimal("99999"),
    )

    with pytest.raises(DataQualityError, match="does not match the exact mark-price candle open"):
        load_verified_funding_slice(
            artifact_root=artifact_root,
            bundle_path=bundle_path,
            registry_path=registry_path,
            symbol=SYMBOL,
            time_start=UTC_START,
            time_end=UTC_END,
            bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
        )


def test_load_verified_funding_slice_rejects_tampered_artifact_bytes(tmp_path: Path) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(tmp_path)
    artifact_path = artifact_root / "canonical" / "funding.parquet"
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")

    with pytest.raises(DataQualityError, match="integrity"):
        load_verified_funding_slice(
            artifact_root=artifact_root,
            bundle_path=bundle_path,
            registry_path=registry_path,
            symbol=SYMBOL,
            time_start=UTC_START,
            time_end=UTC_END,
            bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
        )


def test_load_verified_funding_slice_rejects_event_not_aligned_to_window_bars(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(tmp_path)

    with pytest.raises(DataQualityError, match="align"):
        load_verified_funding_slice(
            artifact_root=artifact_root,
            bundle_path=bundle_path,
            registry_path=registry_path,
            symbol=SYMBOL,
            time_start=UTC_START,
            time_end=UTC_END,
            bar_timestamps=(UTC_START, UTC_START + timedelta(minutes=5)),
        )


def test_verified_cached_window_binds_funding_to_candidate_catalog(tmp_path: Path) -> None:
    artifact_root, bundle_path, registry_path, expected_manifest_hash = _verified_catalog(tmp_path)
    bundle = read_dataset_bundle(bundle_path)
    registry = read_dataset_registry(registry_path)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(UTC_START, periods=3, freq="5min", tz="UTC"),
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100, 101, 102],
        }
    )

    window = load_verified_cached_evaluation_window(
        window_id="verified-oos-001",
        symbol=SYMBOL,
        bundle_hash=bundle.bundle_hash,
        dataset_registry_hash=registry.registry_hash,
        time_start=UTC_START,
        time_end=UTC_END,
        timeframe="5m",
        frame=frame,
        artifact_root=artifact_root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )

    assert window.spec.funding_artifact_hash == expected_manifest_hash
    assert window.funding_slice is not None
    assert window.funding_slice.bundle_hash == bundle.bundle_hash
    assert window.funding_slice.dataset_registry_hash == registry.registry_hash
    assert tuple(window.copy_funding_events()["funding_time"]) == (
        pd.Timestamp(UTC_START),
        pd.Timestamp(UTC_START + timedelta(minutes=10)),
    )


def test_load_verified_funding_slice_rejects_wrong_expected_catalog_hashes(
    tmp_path: Path,
) -> None:
    artifact_root, bundle_path, registry_path, _ = _verified_catalog(tmp_path)

    with pytest.raises(DataQualityError, match="requested provenance"):
        load_verified_funding_slice(
            artifact_root=artifact_root,
            bundle_path=bundle_path,
            registry_path=registry_path,
            symbol=SYMBOL,
            time_start=UTC_START,
            time_end=UTC_END,
            bar_timestamps=tuple(UTC_START + timedelta(minutes=5 * offset) for offset in range(3)),
            expected_bundle_hash="0" * 64,
        )
