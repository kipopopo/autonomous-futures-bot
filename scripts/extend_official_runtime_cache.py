"""Append a contiguous official cache extension without rewriting its history."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
DURATIONS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cache_inputs(
    cache: Path, symbol: str, timeframe: str
) -> tuple[dict[str, Any], Path, pa.Table]:
    manifest_path = cache / timeframe / "manifests" / f"{symbol}-{timeframe}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("symbol") != symbol or manifest.get("timeframe") != timeframe:
        raise ValueError("Cache manifest identity mismatch")
    relative_path = f"canonical/{symbol}-{timeframe}.parquet"
    source = next(
        item for item in manifest["source_files"] if item["relative_path"] == relative_path
    )
    parquet_path = cache / timeframe / relative_path
    if digest(parquet_path) != source["sha256"]:
        raise ValueError(f"Cache parquet hash mismatch: {parquet_path}")
    table = pq.read_table(parquet_path)
    if table.num_rows != source["rows"] or table.num_rows == 0:
        raise ValueError(f"Cache row count is empty or mismatched: {parquet_path}")
    return manifest, manifest_path, table


def _timestamps(table: pa.Table, timeframe: str) -> np.ndarray:
    values = table["timestamp"].cast(pa.int64()).to_numpy(zero_copy_only=False)
    if len(values) == 0 or (len(values) > 1 and np.any(np.diff(values) != DURATIONS[timeframe])):
        raise ValueError(f"Cache has empty or non-contiguous {timeframe} candles")
    return values


def _combined_archives(
    base: list[dict[str, Any]], extension: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    archives = [*base, *extension]
    months = [datetime.strptime(item["month"], "%Y-%m") for item in archives]
    month_numbers = [month.year * 12 + month.month for month in months]
    if len(set(month_numbers)) != len(month_numbers):
        raise ValueError("Base and extension cache provenance overlap")
    if month_numbers != sorted(month_numbers) or any(
        right - left != 1 for left, right in zip(month_numbers, month_numbers[1:], strict=False)
    ):
        raise ValueError("Base and extension archive provenance is not contiguous")
    return archives


def extend_cache(base_cache: Path, extension_cache: Path, output: Path, symbols: list[str]) -> None:
    base_cache, extension_cache, output = (
        base_cache.resolve(),
        extension_cache.resolve(),
        output.resolve(),
    )
    if output.exists():
        raise ValueError(f"Immutable target already exists: {output}")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("At least one unique symbol is required")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temp:
        temporary_output = Path(temp)
        for symbol in symbols:
            for timeframe in DURATIONS:
                base_manifest, base_manifest_path, base_table = _cache_inputs(
                    base_cache, symbol, timeframe
                )
                extension_manifest, extension_manifest_path, extension_table = _cache_inputs(
                    extension_cache, symbol, timeframe
                )
                if base_table.schema != extension_table.schema:
                    raise ValueError(f"Cache schema mismatch for {symbol} {timeframe}")
                if not base_manifest.get("official_archives") or not extension_manifest.get(
                    "official_archives"
                ):
                    raise ValueError("Official archive provenance is missing")
                parser_hash = extension_manifest.get("market_data_parser_sha256")
                if not isinstance(parser_hash, str) or len(parser_hash) != 64:
                    raise ValueError("Extension parser hash is missing")

                base_times = _timestamps(base_table, timeframe)
                extension_times = _timestamps(extension_table, timeframe)
                if extension_times[0] != base_times[-1] + DURATIONS[timeframe]:
                    raise ValueError(f"Cache extension is not adjacent for {symbol} {timeframe}")
                archives = _combined_archives(
                    base_manifest["official_archives"], extension_manifest["official_archives"]
                )
                combined = pa.concat_tables([base_table, extension_table])
                combined_times = _timestamps(combined, timeframe)

                canonical = (
                    temporary_output / timeframe / "canonical" / f"{symbol}-{timeframe}.parquet"
                )
                canonical.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(combined, canonical, compression="zstd")
                manifest = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "derivation": (
                        "verified base cache plus adjacent complete official 1m extension"
                    ),
                    "builder_sha256": digest(Path(__file__)),
                    "market_data_parser_sha256": parser_hash,
                    "official_archives": archives,
                    "input_cache_manifests": {
                        "base": {
                            "path": str(base_manifest_path),
                            "sha256": digest(base_manifest_path),
                            "parquet_sha256": digest(
                                base_cache
                                / timeframe
                                / "canonical"
                                / f"{symbol}-{timeframe}.parquet"
                            ),
                        },
                        "extension": {
                            "path": str(extension_manifest_path),
                            "sha256": digest(extension_manifest_path),
                            "parquet_sha256": digest(
                                extension_cache
                                / timeframe
                                / "canonical"
                                / f"{symbol}-{timeframe}.parquet"
                            ),
                        },
                    },
                    "source_files": [
                        {
                            "relative_path": f"canonical/{symbol}-{timeframe}.parquet",
                            "rows": combined.num_rows,
                            "sha256": digest(canonical),
                        }
                    ],
                    "first_ms": int(combined_times[0]),
                    "last_close_ms": int(combined_times[-1]) + DURATIONS[timeframe],
                }
                manifest_path = (
                    temporary_output
                    / timeframe
                    / "manifests"
                    / f"{symbol}-{timeframe}.manifest.json"
                )
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
        temporary_output.rename(output)

    print(
        json.dumps(
            {
                "event": "OFFICIAL_CACHE_EXTENDED",
                "base_cache": str(base_cache),
                "extension_cache": str(extension_cache),
                "output": str(output),
                "symbols": symbols,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-cache", type=Path, required=True)
    parser.add_argument("--extension-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", action="append", required=True)
    args = parser.parse_args()
    extend_cache(args.base_cache, args.extension_cache, args.output, args.symbol)


if __name__ == "__main__":
    main()
