from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import pandas as pd

from ..domain.errors import DomainViolation
from .manifest import (
    DatasetManifest,
    build_manifest,
    describe_data_file,
    write_manifest,
)
from .parquet import (
    DataQualityError,
    canonicalize_bars,
    read_canonical_parquet,
    write_canonical_parquet,
)

KlineInterval = Literal["5m", "15m"]
INTERVAL_MS: dict[KlineInterval, int] = {"5m": 300_000, "15m": 900_000}
RAW_KLINE_COLUMNS = (
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
)
CANONICAL_KLINE_COLUMNS = (
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
)


def _parse_integer(value: object, *, field: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid integer in {field}: {value!r}") from exc


def _parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid decimal in {field}: {value!r}") from exc


def _interval_delta(interval: KlineInterval) -> timedelta:
    try:
        return timedelta(milliseconds=INTERVAL_MS[interval])
    except KeyError as exc:
        raise DataQualityError(f"unsupported kline interval: {interval}") from exc


def read_kline_csv(path: Path, *, symbol: str, interval: KlineInterval) -> pd.DataFrame:
    interval_ms = INTERVAL_MS.get(interval)
    if interval_ms is None:
        raise DataQualityError(f"unsupported kline interval: {interval}")
    if not symbol:
        raise DataQualityError("symbol must not be empty")

    frame = pd.read_csv(path, dtype=str)
    missing = [column for column in RAW_KLINE_COLUMNS if column not in frame.columns]
    if missing:
        raise DataQualityError(f"missing Binance kline columns: {', '.join(missing)}")

    open_ms = frame["open_time"].map(lambda value: _parse_integer(value, field="open_time"))
    close_ms = frame["close_time"].map(lambda value: _parse_integer(value, field="close_time"))
    expected_close_ms = open_ms + interval_ms - 1
    if not close_ms.eq(expected_close_ms).all():
        raise DataQualityError(f"close_time does not match {interval} candle boundaries")

    canonical = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(open_ms, unit="ms", utc=True),
            "open": frame["open"].map(lambda value: _parse_decimal(value, field="open")),
            "high": frame["high"].map(lambda value: _parse_decimal(value, field="high")),
            "low": frame["low"].map(lambda value: _parse_decimal(value, field="low")),
            "close": frame["close"].map(lambda value: _parse_decimal(value, field="close")),
            "volume": frame["volume"].map(lambda value: _parse_decimal(value, field="volume")),
            "close_time": pd.to_datetime(close_ms, unit="ms", utc=True),
            "quote_volume": frame["quote_volume"].map(
                lambda value: _parse_decimal(value, field="quote_volume")
            ),
            "trades": frame["trades"].map(lambda value: _parse_integer(value, field="trades")),
            "taker_buy_base": frame["taker_buy_base"].map(
                lambda value: _parse_decimal(value, field="taker_buy_base")
            ),
            "taker_buy_quote": frame["taker_buy_quote"].map(
                lambda value: _parse_decimal(value, field="taker_buy_quote")
            ),
        }
    )
    canonical = canonicalize_bars(canonical, interval=_interval_delta(interval))
    return canonical.loc[:, CANONICAL_KLINE_COLUMNS]


def _ensure_immutable_artifact(
    canonical: pd.DataFrame,
    artifact_path: Path,
    *,
    interval: KlineInterval,
) -> None:
    if not artifact_path.exists():
        write_canonical_parquet(canonical, artifact_path, interval=_interval_delta(interval))
        return

    existing = read_canonical_parquet(artifact_path, interval=_interval_delta(interval))
    try:
        pd.testing.assert_frame_equal(existing, canonical)
    except AssertionError as exc:
        raise DomainViolation(f"canonical artifact path is immutable: {artifact_path}") from exc


def build_kline_dataset(
    source_path: Path,
    output_dir: Path,
    *,
    symbol: str,
    interval: KlineInterval,
    code_version: str,
    dependency_lock_hash: str,
    created_at: datetime,
) -> DatasetManifest:
    canonical = read_kline_csv(source_path, symbol=symbol, interval=interval)
    artifact_path = output_dir / "canonical" / f"{symbol}-{interval}.parquet"
    manifest_path = output_dir / "manifests" / f"{symbol}-{interval}.manifest.json"
    _ensure_immutable_artifact(canonical, artifact_path, interval=interval)

    source_file = describe_data_file(
        source_path,
        relative_path=f"raw/{source_path.name}",
        rows=len(canonical),
    )
    canonical_file = describe_data_file(
        artifact_path,
        relative_path=f"canonical/{artifact_path.name}",
        rows=len(canonical),
    )
    manifest = build_manifest(
        symbols=(symbol,),
        source_files=(source_file, canonical_file),
        dataset_interval=interval,
        time_start=canonical["timestamp"].iloc[0].to_pydatetime().astimezone(UTC),
        time_end=canonical["timestamp"].iloc[-1].to_pydatetime().astimezone(UTC),
        created_at=created_at,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
    )
    write_manifest(manifest_path, manifest)
    return manifest


__all__ = [
    "CANONICAL_KLINE_COLUMNS",
    "INTERVAL_MS",
    "RAW_KLINE_COLUMNS",
    "build_kline_dataset",
    "read_kline_csv",
]
