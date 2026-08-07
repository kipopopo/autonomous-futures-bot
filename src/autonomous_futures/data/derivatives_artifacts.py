from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .alignment import (
    FUNDING_COLUMNS,
    MARK_PRICE_COLUMNS,
    canonicalize_funding_rows,
    canonicalize_mark_price_klines,
)
from .builder import KlineInterval
from .manifest import sha256_file
from .parquet import DataQualityError

DerivativeArtifactKind = Literal["funding_rate", "mark_price"]

_EXPECTED_ENDPOINTS: dict[str, str] = {
    "funding_rate": "/fapi/v1/fundingRate",
    "mark_price": "/fapi/v1/markPriceKlines",
}


class DerivativesArtifactManifest(DomainModel):
    manifest_version: Literal[1] = 1
    kind: DerivativeArtifactKind
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    interval: KlineInterval | None = None
    time_start: datetime
    time_end: datetime
    artifact_ref: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=1)
    schema_version: str = Field(min_length=1)
    source: Literal["binance_public_rest"] = "binance_public_rest"
    endpoint_path: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    dependency_lock_hash: str = Field(min_length=1)
    created_at: datetime
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("time_start", "time_end", "created_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("manifest timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("artifact_ref")
    @classmethod
    def artifact_ref_is_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact_ref must be a relative path")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> DerivativesArtifactManifest:
        if self.time_start >= self.time_end:
            raise ValueError("time_start must be before time_end")
        if self.endpoint_path != _EXPECTED_ENDPOINTS[self.kind]:
            raise ValueError(f"endpoint_path does not match {self.kind}")
        if self.kind == "funding_rate" and self.interval is not None:
            raise ValueError("funding_rate interval must be null")
        if self.kind == "mark_price" and self.interval is None:
            raise ValueError("mark_price interval is required")
        return self


def _manifest_content_hash(manifest: DerivativesArtifactManifest) -> str:
    payload = manifest.model_dump(
        mode="json",
        exclude={"created_at", "manifest_hash"},
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _utc_range(time_start: datetime, time_end: datetime) -> tuple[datetime, datetime]:
    values = (time_start, time_end)
    if any(value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value) for value in values):
        raise DataQualityError("artifact time range must be timezone-aware UTC")
    start = time_start.astimezone(UTC)
    end = time_end.astimezone(UTC)
    if start >= end:
        raise DataQualityError("artifact time_start must be before time_end")
    return start, end


def _timestamp_ms(value: object, *, field: str) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise DataQualityError(f"{field} must be timezone-aware UTC")
    return int(timestamp.tz_convert(UTC).value // 1_000_000)


def _canonical_funding_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    time_start: datetime,
    time_end: datetime,
) -> pd.DataFrame:
    missing = sorted(set(FUNDING_COLUMNS).difference(frame.columns))
    if missing:
        raise DataQualityError(f"funding frame is missing columns: {', '.join(missing)}")
    rows = [
        {
            "symbol": row_symbol,
            "fundingTime": _timestamp_ms(funding_time, field="funding_time"),
            "fundingRate": funding_rate,
            "markPrice": funding_mark_price,
        }
        for row_symbol, funding_time, funding_rate, funding_mark_price in frame.loc[
            :, FUNDING_COLUMNS
        ].itertuples(index=False, name=None)
    ]
    return canonicalize_funding_rows(
        rows,
        symbol=symbol,
        start_ms=_timestamp_ms(time_start, field="time_start"),
        end_exclusive_ms=_timestamp_ms(time_end, field="time_end"),
    )


def _canonical_mark_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    interval: KlineInterval,
    time_start: datetime,
    time_end: datetime,
) -> pd.DataFrame:
    missing = sorted(set(MARK_PRICE_COLUMNS).difference(frame.columns))
    if missing:
        raise DataQualityError(f"mark-price frame is missing columns: {', '.join(missing)}")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    start_timestamp = pd.Timestamp(time_start)
    end_timestamp = pd.Timestamp(time_end)
    if ((timestamps < start_timestamp) | (timestamps >= end_timestamp)).any():
        raise DataQualityError("mark-price bar is outside the requested time range")
    rows = [
        [
            _timestamp_ms(timestamp, field="timestamp"),
            open_price,
            high,
            low,
            close,
            _timestamp_ms(close_time, field="close_time"),
        ]
        for row_symbol, timestamp, open_price, high, low, close, close_time in frame.loc[
            :, MARK_PRICE_COLUMNS
        ].itertuples(index=False, name=None)
        if row_symbol == symbol
    ]
    if len(rows) != len(frame):
        raise DataQualityError("mark-price frame symbol does not match requested symbol")
    return canonicalize_mark_price_klines(
        rows,
        symbol=symbol,
        interval=interval,
        end_exclusive_ms=_timestamp_ms(time_end, field="time_end"),
    )


def _write_frame_once(canonical: pd.DataFrame, path: Path) -> None:
    if path.exists():
        existing = pd.read_parquet(path, engine="pyarrow")
        try:
            pd.testing.assert_frame_equal(
                existing.reset_index(drop=True),
                canonical.reset_index(drop=True),
                check_dtype=False,
                check_exact=True,
            )
        except AssertionError as exc:
            raise DomainViolation(f"canonical artifact path is immutable: {path}") from exc
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        table = pa.Table.from_pandas(canonical, preserve_index=False)
        pq.write_table(table, temporary_path, compression="zstd")
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _build_manifest(
    *,
    kind: DerivativeArtifactKind,
    symbol: str,
    interval: KlineInterval | None,
    time_start: datetime,
    time_end: datetime,
    artifact_ref: str,
    artifact_path: Path,
    rows: int,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
) -> DerivativesArtifactManifest:
    start, end = _utc_range(time_start, time_end)
    provisional = DerivativesArtifactManifest(
        kind=kind,
        symbol=symbol,
        interval=interval,
        time_start=start,
        time_end=end,
        artifact_ref=artifact_ref,
        artifact_sha256=sha256_file(artifact_path),
        rows=rows,
        schema_version=f"derivatives-artifact-v1:{kind}",
        endpoint_path=_EXPECTED_ENDPOINTS[kind],
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
        created_at=created_at.astimezone(UTC),
        manifest_hash="0" * 64,
    )
    return provisional.model_copy(update={"manifest_hash": _manifest_content_hash(provisional)})


def read_derivatives_artifact_manifest(
    path: Path, *, artifact_path: Path | None = None
) -> DerivativesArtifactManifest:
    manifest = DerivativesArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if _manifest_content_hash(manifest) != manifest.manifest_hash:
        raise DomainViolation(f"derivatives artifact manifest hash mismatch: {path}")
    if artifact_path is not None and sha256_file(artifact_path) != manifest.artifact_sha256:
        raise DomainViolation(f"artifact hash mismatch: {artifact_path}")
    return manifest


def _write_manifest_once(
    path: Path, manifest: DerivativesArtifactManifest, artifact_path: Path
) -> None:
    if path.exists():
        existing = read_derivatives_artifact_manifest(path, artifact_path=artifact_path)
        if existing != manifest:
            raise DomainViolation(f"derivatives manifest path is immutable: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def _persist(
    canonical: pd.DataFrame,
    *,
    kind: DerivativeArtifactKind,
    symbol: str,
    interval: KlineInterval | None,
    artifact_path: Path,
    manifest_path: Path,
    artifact_ref: str,
    time_start: datetime,
    time_end: datetime,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
) -> DerivativesArtifactManifest:
    _write_frame_once(canonical, artifact_path)
    manifest = _build_manifest(
        kind=kind,
        symbol=symbol,
        interval=interval,
        time_start=time_start,
        time_end=time_end,
        artifact_ref=artifact_ref,
        artifact_path=artifact_path,
        rows=len(canonical),
        created_at=created_at,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
    )
    _write_manifest_once(manifest_path, manifest, artifact_path)
    return manifest


def write_funding_artifact(
    frame: pd.DataFrame,
    artifact_path: Path,
    manifest_path: Path,
    *,
    artifact_ref: str,
    symbol: str,
    time_start: datetime,
    time_end: datetime,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
) -> DerivativesArtifactManifest:
    start, end = _utc_range(time_start, time_end)
    canonical = _canonical_funding_frame(
        frame,
        symbol=symbol,
        time_start=start,
        time_end=end,
    )
    return _persist(
        canonical,
        kind="funding_rate",
        symbol=symbol,
        interval=None,
        artifact_path=artifact_path,
        manifest_path=manifest_path,
        artifact_ref=artifact_ref,
        time_start=start,
        time_end=end,
        created_at=created_at,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
    )


def read_funding_artifact(
    path: Path, *, symbol: str, time_start: datetime, time_end: datetime
) -> pd.DataFrame:
    start, end = _utc_range(time_start, time_end)
    return _canonical_funding_frame(
        pd.read_parquet(path, engine="pyarrow"),
        symbol=symbol,
        time_start=start,
        time_end=end,
    )


def write_mark_price_artifact(
    frame: pd.DataFrame,
    artifact_path: Path,
    manifest_path: Path,
    *,
    artifact_ref: str,
    symbol: str,
    interval: KlineInterval,
    time_start: datetime,
    time_end: datetime,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
) -> DerivativesArtifactManifest:
    start, end = _utc_range(time_start, time_end)
    canonical = _canonical_mark_frame(
        frame,
        symbol=symbol,
        interval=interval,
        time_start=start,
        time_end=end,
    )
    return _persist(
        canonical,
        kind="mark_price",
        symbol=symbol,
        interval=interval,
        artifact_path=artifact_path,
        manifest_path=manifest_path,
        artifact_ref=artifact_ref,
        time_start=start,
        time_end=end,
        created_at=created_at,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
    )


def read_mark_price_artifact(
    path: Path,
    *,
    symbol: str,
    interval: KlineInterval,
    time_start: datetime,
    time_end: datetime,
) -> pd.DataFrame:
    start, end = _utc_range(time_start, time_end)
    return _canonical_mark_frame(
        pd.read_parquet(path, engine="pyarrow"),
        symbol=symbol,
        interval=interval,
        time_start=start,
        time_end=end,
    )


__all__ = [
    "DerivativesArtifactManifest",
    "read_derivatives_artifact_manifest",
    "read_funding_artifact",
    "read_mark_price_artifact",
    "write_funding_artifact",
    "write_mark_price_artifact",
]
