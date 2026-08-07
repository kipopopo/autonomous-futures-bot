from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .quality import DataQualityError, canonicalize_bars, find_timestamp_gaps


def write_canonical_parquet(
    frame: pd.DataFrame,
    path: Path,
    *,
    interval: timedelta,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    canonical = canonicalize_bars(
        frame,
        interval=interval,
        timestamp_column=timestamp_column,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(canonical, preserve_index=False)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        pq.write_table(table, temporary_path, compression="zstd")
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return canonical


def read_canonical_parquet(
    path: Path,
    *,
    interval: timedelta,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    frame = pd.read_parquet(path, engine="pyarrow")
    return canonicalize_bars(
        frame,
        interval=interval,
        timestamp_column=timestamp_column,
    )


__all__ = [
    "DataQualityError",
    "canonicalize_bars",
    "find_timestamp_gaps",
    "read_canonical_parquet",
    "write_canonical_parquet",
]
