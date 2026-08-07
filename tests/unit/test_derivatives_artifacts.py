from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.derivatives_artifacts import (
    DerivativesArtifactManifest,
    read_derivatives_artifact_manifest,
    read_funding_artifact,
    read_mark_price_artifact,
    write_funding_artifact,
    write_mark_price_artifact,
)
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation

START = datetime(2026, 8, 7, tzinfo=UTC)
END = datetime(2026, 8, 7, 8, 0, 0, 1000, tzinfo=UTC)
CREATED = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _funding_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "funding_time": pd.to_datetime(
                ["2026-08-07T00:00:00Z", "2026-08-07T08:00:00Z"], utc=True
            ),
            "funding_rate": [Decimal("0.00010000"), Decimal("-0.00007500")],
            "funding_mark_price": [Decimal("99.87500000"), Decimal("100.12500000")],
        }
    )


def _mark_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "timestamp": pd.to_datetime(["2026-08-07T00:00:00Z", "2026-08-07T00:05:00Z"], utc=True),
            "open": [Decimal("100"), Decimal("100.5")],
            "high": [Decimal("101"), Decimal("102")],
            "low": [Decimal("99"), Decimal("100")],
            "close": [Decimal("100.5"), Decimal("101.5")],
            "close_time": pd.to_datetime(
                ["2026-08-07T00:04:59.999Z", "2026-08-07T00:09:59.999Z"], utc=True
            ),
        }
    )


def test_funding_artifact_roundtrips_decimal_values_and_manifest(tmp_path: Path) -> None:
    artifact_path = tmp_path / "canonical" / "BTCUSDT-funding.parquet"
    manifest_path = tmp_path / "manifests" / "BTCUSDT-funding.json"

    manifest = write_funding_artifact(
        _funding_frame(),
        artifact_path,
        manifest_path,
        artifact_ref="canonical/BTCUSDT-funding.parquet",
        symbol="BTCUSDT",
        time_start=START,
        time_end=END,
        created_at=CREATED,
        code_version="test",
        dependency_lock_hash="uv.lock",
    )
    restored = read_funding_artifact(
        artifact_path, symbol="BTCUSDT", time_start=START, time_end=END
    )

    assert isinstance(manifest, DerivativesArtifactManifest)
    assert manifest.kind == "funding_rate"
    assert manifest.interval is None
    assert manifest.rows == 2
    assert manifest.artifact_sha256 != "0" * 64
    assert manifest.manifest_hash != "0" * 64
    assert restored["funding_rate"].tolist() == [
        Decimal("0.00010000"),
        Decimal("-0.00007500"),
    ]
    assert (
        read_derivatives_artifact_manifest(manifest_path, artifact_path=artifact_path) == manifest
    )


def test_mark_price_artifact_roundtrips_closed_bars_and_manifest(tmp_path: Path) -> None:
    artifact_path = tmp_path / "canonical" / "BTCUSDT-mark-5m.parquet"
    manifest_path = tmp_path / "manifests" / "BTCUSDT-mark-5m.json"

    manifest = write_mark_price_artifact(
        _mark_frame(),
        artifact_path,
        manifest_path,
        artifact_ref="canonical/BTCUSDT-mark-5m.parquet",
        symbol="BTCUSDT",
        interval="5m",
        time_start=START,
        time_end=datetime(2026, 8, 7, 0, 10, tzinfo=UTC),
        created_at=CREATED,
        code_version="test",
        dependency_lock_hash="uv.lock",
    )
    restored = read_mark_price_artifact(
        artifact_path,
        symbol="BTCUSDT",
        interval="5m",
        time_start=START,
        time_end=datetime(2026, 8, 7, 0, 10, tzinfo=UTC),
    )

    assert manifest.kind == "mark_price"
    assert manifest.interval == "5m"
    assert restored["close"].tolist() == [Decimal("100.5"), Decimal("101.5")]
    assert restored["close_time"].tolist() == [
        pd.Timestamp("2026-08-07T00:04:59.999Z"),
        pd.Timestamp("2026-08-07T00:09:59.999Z"),
    ]


def test_derivative_artifacts_are_write_once_and_tamper_evident(tmp_path: Path) -> None:
    artifact_path = tmp_path / "canonical" / "BTCUSDT-funding.parquet"
    manifest_path = tmp_path / "manifests" / "BTCUSDT-funding.json"
    frame = _funding_frame()
    manifest = write_funding_artifact(
        frame,
        artifact_path,
        manifest_path,
        artifact_ref="canonical/BTCUSDT-funding.parquet",
        symbol="BTCUSDT",
        time_start=START,
        time_end=END,
        created_at=CREATED,
        code_version="test",
        dependency_lock_hash="uv.lock",
    )

    assert (
        write_funding_artifact(
            frame,
            artifact_path,
            manifest_path,
            artifact_ref="canonical/BTCUSDT-funding.parquet",
            symbol="BTCUSDT",
            time_start=START,
            time_end=END,
            created_at=CREATED,
            code_version="test",
            dependency_lock_hash="uv.lock",
        )
        == manifest
    )

    changed = frame.copy()
    changed.loc[0, "funding_rate"] = Decimal("0.00020000")
    with pytest.raises(DomainViolation, match="immutable"):
        write_funding_artifact(
            changed,
            artifact_path,
            manifest_path,
            artifact_ref="canonical/BTCUSDT-funding.parquet",
            symbol="BTCUSDT",
            time_start=START,
            time_end=END,
            created_at=CREATED,
            code_version="test",
            dependency_lock_hash="uv.lock",
        )

    artifact_path.write_bytes(artifact_path.read_bytes() + b"tamper")
    with pytest.raises(DomainViolation, match="artifact hash mismatch"):
        read_derivatives_artifact_manifest(manifest_path, artifact_path=artifact_path)


def test_mark_artifact_rejects_non_closed_bar(tmp_path: Path) -> None:
    frame = _mark_frame()
    frame.loc[1, "close_time"] = pd.Timestamp("2026-08-07T00:10:00Z")

    with pytest.raises(DataQualityError, match="close_time"):
        write_mark_price_artifact(
            frame,
            tmp_path / "mark.parquet",
            tmp_path / "mark.json",
            artifact_ref="mark.parquet",
            symbol="BTCUSDT",
            interval="5m",
            time_start=START,
            time_end=datetime(2026, 8, 7, 0, 10, tzinfo=UTC),
            created_at=CREATED,
            code_version="test",
            dependency_lock_hash="uv.lock",
        )


def test_mark_artifact_rejects_bar_before_requested_start(tmp_path: Path) -> None:
    frame = _mark_frame()
    frame.loc[0, "timestamp"] = pd.Timestamp("2026-08-06T23:55:00Z")
    frame.loc[0, "close_time"] = pd.Timestamp("2026-08-06T23:59:59.999Z")

    with pytest.raises(DataQualityError, match="outside the requested"):
        write_mark_price_artifact(
            frame,
            tmp_path / "mark.parquet",
            tmp_path / "mark.json",
            artifact_ref="mark.parquet",
            symbol="BTCUSDT",
            interval="5m",
            time_start=START,
            time_end=datetime(2026, 8, 7, 0, 10, tzinfo=UTC),
            created_at=CREATED,
            code_version="test",
            dependency_lock_hash="uv.lock",
        )
