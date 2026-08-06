from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.builder import build_kline_dataset, read_kline_csv
from autonomous_futures.data.manifest import read_manifest
from autonomous_futures.data.parquet import DataQualityError, read_canonical_parquet


def write_kline_csv(
    path: Path,
    open_times: tuple[int, ...],
    *,
    bad_close_time: bool = False,
) -> None:
    fields = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, open_time in enumerate(open_times):
            close_time = open_time + (299_999 if not bad_close_time or index else 299_998)
            writer.writerow(
                {
                    "open_time": open_time,
                    "open": f"{100 + index}.00",
                    "high": f"{101 + index}.00",
                    "low": f"{99 + index}.00",
                    "close": f"{100.50 + index:.2f}",
                    "volume": "12.345",
                    "close_time": close_time,
                    "quote_volume": "1234.500",
                    "trades": 10 + index,
                    "taker_buy_base": "6.000",
                    "taker_buy_quote": "600.000",
                    "ignore": "0",
                }
            )


def test_kline_builder_creates_canonical_parquet_and_bound_manifest(tmp_path) -> None:
    source = tmp_path / "BTCUSDT-5m.csv"
    output_dir = tmp_path / "dataset"
    write_kline_csv(source, (1_725_504_000_000, 1_725_504_300_000, 1_725_504_600_000))

    manifest = build_kline_dataset(
        source,
        output_dir,
        symbol="BTCUSDT",
        interval="5m",
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
        created_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
    )

    artifact = output_dir / "canonical" / "BTCUSDT-5m.parquet"
    manifest_path = output_dir / "manifests" / "BTCUSDT-5m.manifest.json"
    canonical = read_canonical_parquet(artifact, interval=pd.Timedelta(minutes=5).to_pytimedelta())

    assert artifact.exists()
    assert manifest_path.exists()
    assert manifest.dataset_interval == "5m"
    assert canonical["timestamp"].tolist() == [
        pd.Timestamp("2024-09-05T02:40:00Z"),
        pd.Timestamp("2024-09-05T02:45:00Z"),
        pd.Timestamp("2024-09-05T02:50:00Z"),
    ]
    assert list(canonical.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    assert {file.relative_path for file in manifest.source_files} == {
        "canonical/BTCUSDT-5m.parquet",
        "raw/BTCUSDT-5m.csv",
    }
    assert read_manifest(manifest_path) == manifest


def test_csv_reader_rejects_close_time_contract_violation(tmp_path) -> None:
    source = tmp_path / "BTCUSDT-5m.csv"
    write_kline_csv(source, (1_725_504_000_000,), bad_close_time=True)

    with pytest.raises(DataQualityError, match="close_time"):
        read_kline_csv(source, symbol="BTCUSDT", interval="5m")


def test_kline_builder_surfaces_gaps_and_writes_no_artifact(tmp_path) -> None:
    source = tmp_path / "BTCUSDT-5m.csv"
    output_dir = tmp_path / "dataset"
    write_kline_csv(source, (1_725_504_000_000, 1_725_504_600_000))

    with pytest.raises(DataQualityError, match="gap"):
        build_kline_dataset(
            source,
            output_dir,
            symbol="BTCUSDT",
            interval="5m",
            code_version="test-code",
            dependency_lock_hash="sha256:lock",
            created_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
        )

    assert not (output_dir / "canonical" / "BTCUSDT-5m.parquet").exists()
    assert not (output_dir / "manifests" / "BTCUSDT-5m.manifest.json").exists()
