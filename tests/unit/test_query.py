from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.api.artifacts import inspect_artifact_entry
from autonomous_futures.api.query import (
    QueryCoverageError,
    QueryLimitError,
    query_component_rows,
)
from autonomous_futures.data.manifest import build_manifest, describe_data_file, write_manifest
from autonomous_futures.data.parquet import write_canonical_parquet
from autonomous_futures.data.registry import DatasetRegistryEntry

START = datetime(2026, 8, 7, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry(*, manifest_hash: str, artifact_ref: str) -> DatasetRegistryEntry:
    return DatasetRegistryEntry(
        kind="kline",
        symbols=(SYMBOL,),
        interval="5m",
        time_start=START,
        time_end=START + timedelta(minutes=10),
        observed_at=START + timedelta(hours=1),
        schema_version="kline-v1",
        content_hash=manifest_hash,
        artifact_ref=artifact_ref,
        endpoint_path="/fapi/v1/klines",
        provenance=("binance_public_rest", "unsigned", "query_fixture"),
    )


def _write_kline_artifact(tmp_path: Path) -> tuple[DatasetRegistryEntry, Path]:
    artifact_root = tmp_path / "artifacts"
    dataset_root = artifact_root / SYMBOL
    raw_path = dataset_root / "raw" / "BTCUSDT-5m.csv"
    parquet_path = dataset_root / "canonical" / "BTCUSDT-5m.parquet"
    manifest_path = dataset_root / "manifests" / "BTCUSDT-5m.manifest.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("raw fixture\n", encoding="utf-8")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [START, START + timedelta(minutes=5), START + timedelta(minutes=10)],
                utc=True,
            ),
            "close": [Decimal("100.125"), Decimal("100.250"), Decimal("100.500")],
        }
    )
    write_canonical_parquet(frame, parquet_path, interval=timedelta(minutes=5))
    manifest = build_manifest(
        symbols=(SYMBOL,),
        source_files=(
            describe_data_file(raw_path, relative_path="raw/BTCUSDT-5m.csv", rows=3),
            describe_data_file(
                parquet_path,
                relative_path="canonical/BTCUSDT-5m.parquet",
                rows=3,
            ),
        ),
        time_start=START,
        time_end=START + timedelta(minutes=10),
        created_at=START + timedelta(hours=1),
        code_version="test",
        dependency_lock_hash="uv.lock",
        dataset_interval="5m",
    )
    write_manifest(manifest_path, manifest)
    return (
        _entry(
            manifest_hash=manifest.manifest_hash,
            artifact_ref=f"{SYMBOL}/manifests/{manifest_path.name}",
        ),
        artifact_root,
    )


def test_query_returns_bounded_rows_with_decimal_and_utc_json_values(tmp_path: Path) -> None:
    entry, artifact_root = _write_kline_artifact(tmp_path)
    inspection = inspect_artifact_entry(artifact_root, entry)

    rows = query_component_rows(
        artifact_root,
        entry,
        inspection,
        start=START + timedelta(minutes=5),
        end=START + timedelta(minutes=15),
        limit=2,
    )

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2026-08-07T00:05:00Z"
    assert rows[0]["close"] == "100.250"
    assert rows[1]["timestamp"] == "2026-08-07T00:10:00Z"


def test_query_rejects_ranges_outside_component_coverage(tmp_path: Path) -> None:
    entry, artifact_root = _write_kline_artifact(tmp_path)
    inspection = inspect_artifact_entry(artifact_root, entry)

    with pytest.raises(QueryCoverageError, match="coverage"):
        query_component_rows(
            artifact_root,
            entry,
            inspection,
            start=START - timedelta(minutes=5),
            end=START + timedelta(minutes=5),
            limit=10,
        )


def test_query_rejects_result_sets_over_hard_limit(tmp_path: Path) -> None:
    entry, artifact_root = _write_kline_artifact(tmp_path)
    inspection = inspect_artifact_entry(artifact_root, entry)

    with pytest.raises(QueryLimitError, match="limit"):
        query_component_rows(
            artifact_root,
            entry,
            inspection,
            start=START,
            end=START + timedelta(minutes=15),
            limit=2,
        )
