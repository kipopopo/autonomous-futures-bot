from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.extend_official_runtime_cache import DURATIONS, digest, extend_cache

SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        *[(field, pa.decimal128(38, 18)) for field in ("open", "high", "low", "close", "volume")],
        ("close_time", pa.timestamp("ms", tz="UTC")),
    ]
)


def _write_cache(root: Path, *, symbol: str, start_factor: int, months: list[str]) -> None:
    for timeframe, duration in DURATIONS.items():
        timestamps = [start_factor * duration + index * duration for index in range(2)]
        rows = [
            {
                "timestamp": datetime.fromtimestamp(timestamp / 1000, UTC),
                "open": Decimal("10.0"),
                "high": Decimal("11.0"),
                "low": Decimal("9.0"),
                "close": Decimal("10.5"),
                "volume": Decimal("2.0"),
                "close_time": datetime.fromtimestamp((timestamp + duration - 1) / 1000, UTC),
            }
            for timestamp in timestamps
        ]
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        parquet = root / timeframe / "canonical" / f"{symbol}-{timeframe}.parquet"
        parquet.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, parquet, compression="zstd")
        manifest = {
            "symbol": symbol,
            "timeframe": timeframe,
            "builder_sha256": "a" * 64,
            "market_data_parser_sha256": "b" * 64,
            "official_archives": [
                {
                    "symbol": symbol,
                    "timeframe": "1m",
                    "month": month,
                    "sha256": hashlib.sha256(month.encode()).hexdigest(),
                }
                for month in months
            ],
            "source_files": [
                {
                    "relative_path": f"canonical/{symbol}-{timeframe}.parquet",
                    "rows": table.num_rows,
                    "sha256": digest(parquet),
                }
            ],
        }
        manifest_path = root / timeframe / "manifests" / f"{symbol}-{timeframe}.manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_extends_verified_candles_and_preserves_archive_provenance(tmp_path: Path) -> None:
    base = tmp_path / "base"
    extension = tmp_path / "extension"
    output = tmp_path / "combined"
    _write_cache(base, symbol="TESTUSDT", start_factor=0, months=["2026-05", "2026-06"])
    _write_cache(extension, symbol="TESTUSDT", start_factor=2, months=["2026-07", "2026-08"])

    extend_cache(base, extension, output, ["TESTUSDT"])

    table = pq.read_table(output / "5m/canonical/TESTUSDT-5m.parquet")
    assert table.num_rows == 4
    manifest = json.loads((output / "5m/manifests/TESTUSDT-5m.manifest.json").read_text())
    assert [item["month"] for item in manifest["official_archives"]] == [
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
    ]
    assert manifest["market_data_parser_sha256"] == "b" * 64
    assert manifest["source_files"][0]["sha256"] == digest(
        output / "5m/canonical/TESTUSDT-5m.parquet"
    )


def test_rejects_a_non_adjacent_extension_without_writing_output(tmp_path: Path) -> None:
    base = tmp_path / "base"
    extension = tmp_path / "extension"
    output = tmp_path / "combined"
    _write_cache(base, symbol="TESTUSDT", start_factor=0, months=["2026-05"])
    _write_cache(extension, symbol="TESTUSDT", start_factor=3, months=["2026-06"])

    with pytest.raises(ValueError, match="not adjacent"):
        extend_cache(base, extension, output, ["TESTUSDT"])

    assert not output.exists()
