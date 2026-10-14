"""Build immutable Decimal higher-timeframe candles from verified official 1m observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research import official_market_data  # noqa: E402

DURATIONS = {"5m": 300000, "15m": 900000, "1h": 3600000}
SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        *[(field, pa.decimal128(38, 18)) for field in ("open", "high", "low", "close", "volume")],
        ("close_time", pa.timestamp("ms", tz="UTC")),
    ]
)


def build(root: Path, output: Path, symbol: str) -> None:
    provenance = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / symbol).glob("*.manifest.json"))
    ]
    if not provenance:
        raise ValueError("Official minute provenance is missing")
    writers: dict[str, pq.ParquetWriter] = {}
    targets: dict[str, Path] = {}
    buckets: dict[str, dict[str, Any]] = {}
    pending: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in DURATIONS}
    counts = {timeframe: 0 for timeframe in DURATIONS}
    try:
        for timeframe in DURATIONS:
            target = output / timeframe / "canonical" / f"{symbol}-{timeframe}.parquet"
            if target.exists():
                raise ValueError(f"Immutable target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            targets[timeframe] = target
            writers[timeframe] = pq.ParquetWriter(
                target.with_suffix(".parquet.tmp"), SCHEMA, compression="zstd"
            )
        for bar in official_market_data.official_minutes(root, symbol):
            for timeframe, duration in DURATIONS.items():
                start = bar.timestamp_ms // duration * duration
                bucket = buckets.get(timeframe)
                if bucket is None or bucket["timestamp"] != start:
                    bucket = {
                        "timestamp": start,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": Decimal("0"),
                        "minutes": 0,
                    }
                    buckets[timeframe] = bucket
                bucket["high"] = max(bucket["high"], bar.high)
                bucket["low"] = min(bucket["low"], bar.low)
                bucket["close"] = bar.close
                bucket["volume"] += bar.volume
                bucket["minutes"] += 1
                if bar.timestamp_ms + 60000 != start + duration:
                    continue
                if bucket.pop("minutes") == duration // 60000:
                    bucket["close_time"] = start + duration - 1
                    pending[timeframe].append(dict(bucket))
                    counts[timeframe] += 1
                    if len(pending[timeframe]) >= 4096:
                        writers[timeframe].write_table(
                            pa.Table.from_pylist(pending[timeframe], schema=SCHEMA)
                        )
                        pending[timeframe].clear()
                buckets.pop(timeframe)
        for timeframe, writer in writers.items():
            if pending[timeframe]:
                writer.write_table(pa.Table.from_pylist(pending[timeframe], schema=SCHEMA))
            writer.close()
            target = targets[timeframe]
            target.with_suffix(".parquet.tmp").replace(target)
            manifest = {
                "symbol": symbol,
                "timeframe": timeframe,
                "derivation": "complete contiguous official 1m candles",
                "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "market_data_parser_sha256": hashlib.sha256(
                    Path(official_market_data.__file__).read_bytes()
                ).hexdigest(),
                "official_archives": provenance,
                "source_files": [
                    {
                        "relative_path": f"canonical/{target.name}",
                        "rows": counts[timeframe],
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    }
                ],
            }
            manifest_path = output / timeframe / "manifests" / f"{symbol}-{timeframe}.manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            if manifest_path.exists():
                raise ValueError("Immutable cache manifest exists")
            manifest_path.write_bytes(
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
            )
        print(
            json.dumps(
                {
                    "event": "OFFICIAL_CACHE_BUILT",
                    "symbol": symbol,
                    "rows": counts,
                    "root": str(output),
                }
            ),
            flush=True,
        )
    finally:
        for writer in writers.values():
            writer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REPO / "research/official-archives/1m")
    parser.add_argument(
        "--output", type=Path, default=REPO / "research/immutable-data/runtime-official-20261013"
    )
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()
    symbols = args.symbol or sorted(path.name for path in args.source.iterdir() if path.is_dir())
    for symbol in symbols:
        build(args.source, args.output, symbol)


if __name__ == "__main__":
    main()
