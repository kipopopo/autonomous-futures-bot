from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.data.collection import (
    build_kline_collection,
    read_collection_manifest,
)
from autonomous_futures.data.parquet import DataQualityError

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def write_kline_csv(path: Path, open_times: tuple[int, ...]) -> None:
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
            writer.writerow(
                {
                    "open_time": open_time,
                    "open": f"{100 + index}.00",
                    "high": f"{101 + index}.00",
                    "low": f"{99 + index}.00",
                    "close": f"{100.50 + index:.2f}",
                    "volume": "12.345",
                    "close_time": open_time + 299_999,
                    "quote_volume": "1234.500",
                    "trades": 10 + index,
                    "taker_buy_base": "6.000",
                    "taker_buy_quote": "600.000",
                    "ignore": "0",
                }
            )


def source_set(tmp_path: Path, *, bad_eth_gap: bool = False) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for symbol in SYMBOLS:
        start = 1_725_504_000_000
        times = (
            start,
            start + 300_000,
            start + (600_000 if not bad_eth_gap or symbol != "ETHUSDT" else 900_000),
        )
        path = tmp_path / f"{symbol}-5m.csv"
        write_kline_csv(path, times)
        paths[symbol] = path
    return paths


def test_collection_builds_sorted_children_and_stable_manifest(tmp_path) -> None:
    sources = source_set(tmp_path)
    output_dir = tmp_path / "collection"
    created_at = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)

    first = build_kline_collection(
        sources,
        output_dir,
        interval="5m",
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
        created_at=created_at,
    )
    second = build_kline_collection(
        sources,
        output_dir,
        interval="5m",
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
        created_at=created_at,
    )

    collection_path = output_dir / "manifests" / "collection-5m.manifest.json"
    assert first.symbols == SYMBOLS
    assert first.dataset_interval == "5m"
    assert tuple(child.symbols[0] for child in first.datasets) == SYMBOLS
    assert first.collection_hash == second.collection_hash
    assert read_collection_manifest(collection_path) == first
    assert all((output_dir / "canonical" / f"{symbol}-5m.parquet").exists() for symbol in SYMBOLS)


def test_collection_preflights_all_symbols_before_writing(tmp_path) -> None:
    sources = source_set(tmp_path, bad_eth_gap=True)
    output_dir = tmp_path / "collection"

    with pytest.raises(DataQualityError, match="gap"):
        build_kline_collection(
            sources,
            output_dir,
            interval="5m",
            code_version="test-code",
            dependency_lock_hash="sha256:lock",
            created_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
        )

    assert not output_dir.exists()
