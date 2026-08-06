from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from autonomous_futures.data.manifest import (
    DataFileManifest,
    build_manifest,
    describe_data_file,
    read_manifest,
    write_manifest,
)
from autonomous_futures.data.parquet import (
    DataQualityError,
    canonicalize_bars,
    read_canonical_parquet,
    write_canonical_parquet,
)
from autonomous_futures.data.public_collector import (
    CONTEXT_INTERVAL,
    PRIMARY_INTERVAL,
    build_public_url,
    fully_closed_end_ms,
)
from autonomous_futures.domain.errors import DomainViolation


def bars(*timestamps: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(value) for value in timestamps],
            "open": [Decimal("100"), Decimal("101"), Decimal("102")][: len(timestamps)],
            "close": [Decimal("101"), Decimal("102"), Decimal("103")][: len(timestamps)],
        }
    )


def test_canonical_parquet_sorts_and_rebuilds_identically(tmp_path) -> None:
    frame = bars(
        "2026-08-06T00:05:00+00:00",
        "2026-08-06T00:00:00+00:00",
        "2026-08-06T00:10:00+00:00",
    )
    artifact = tmp_path / "BTCUSDT-5m.parquet"

    written = write_canonical_parquet(frame, artifact, interval=timedelta(minutes=5))
    rebuilt = read_canonical_parquet(artifact, interval=timedelta(minutes=5))

    assert written["timestamp"].tolist() == [
        pd.Timestamp("2026-08-06T00:00:00Z"),
        pd.Timestamp("2026-08-06T00:05:00Z"),
        pd.Timestamp("2026-08-06T00:10:00Z"),
    ]
    pd.testing.assert_frame_equal(written, rebuilt)


def test_canonicalizer_rejects_naive_duplicate_and_gap_timestamps() -> None:
    with pytest.raises(DataQualityError, match="UTC"):
        canonicalize_bars(bars("2026-08-06T00:00:00"), interval=timedelta(minutes=5))

    duplicate = bars(
        "2026-08-06T00:00:00+00:00",
        "2026-08-06T00:00:00+00:00",
    )
    with pytest.raises(DataQualityError, match="duplicate"):
        canonicalize_bars(duplicate, interval=timedelta(minutes=5))

    gap = bars(
        "2026-08-06T00:00:00+00:00",
        "2026-08-06T00:10:00+00:00",
    )
    with pytest.raises(DataQualityError, match="gap"):
        canonicalize_bars(gap, interval=timedelta(minutes=5))


def test_manifest_hash_is_stable_and_changes_when_artifact_changes(tmp_path) -> None:
    artifact = tmp_path / "BTCUSDT-5m.parquet"
    frame = bars(
        "2026-08-06T00:00:00+00:00",
        "2026-08-06T00:05:00+00:00",
        "2026-08-06T00:10:00+00:00",
    )
    write_canonical_parquet(frame, artifact, interval=timedelta(minutes=5))
    source = describe_data_file(artifact, relative_path="BTCUSDT-5m.parquet", rows=len(frame))
    fixed_created_at = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)

    first = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(source,),
        time_start=frame["timestamp"].min().to_pydatetime(),
        time_end=frame["timestamp"].max().to_pydatetime(),
        created_at=fixed_created_at,
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
    )
    second = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(source,),
        time_start=frame["timestamp"].min().to_pydatetime(),
        time_end=frame["timestamp"].max().to_pydatetime(),
        created_at=fixed_created_at,
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
    )
    assert first.manifest_hash == second.manifest_hash

    changed = frame.copy()
    changed.loc[2, "close"] = Decimal("999")
    write_canonical_parquet(changed, artifact, interval=timedelta(minutes=5))
    changed_source = describe_data_file(
        artifact,
        relative_path="BTCUSDT-5m.parquet",
        rows=len(changed),
    )
    changed_manifest = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(changed_source,),
        time_start=frame["timestamp"].min().to_pydatetime(),
        time_end=frame["timestamp"].max().to_pydatetime(),
        created_at=fixed_created_at,
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
    )
    assert changed_manifest.manifest_hash != first.manifest_hash


def test_manifest_file_is_immutable_after_first_write(tmp_path) -> None:
    manifest_path = tmp_path / "dataset.manifest.json"
    created_at = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)
    source = DataFileManifest(
        relative_path="BTCUSDT-5m.parquet",
        sha256="a" * 64,
        rows=3,
    )
    manifest = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(source,),
        time_start=datetime(2026, 8, 6, 0, 0, tzinfo=UTC),
        time_end=datetime(2026, 8, 6, 0, 10, tzinfo=UTC),
        created_at=created_at,
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
    )

    write_manifest(manifest_path, manifest)
    assert read_manifest(manifest_path) == manifest
    write_manifest(manifest_path, manifest)

    changed = manifest.model_copy(update={"code_version": "different-code"})
    with pytest.raises(DomainViolation, match="immutable"):
        write_manifest(manifest_path, changed)


def test_manifest_reader_rejects_tampered_content(tmp_path) -> None:
    manifest_path = tmp_path / "dataset.manifest.json"
    manifest = build_manifest(
        symbols=("BTCUSDT",),
        source_files=(
            DataFileManifest(
                relative_path="BTCUSDT-5m.parquet",
                sha256="a" * 64,
                rows=3,
            ),
        ),
        time_start=datetime(2026, 8, 6, 0, 0, tzinfo=UTC),
        time_end=datetime(2026, 8, 6, 0, 10, tzinfo=UTC),
        created_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
    )
    write_manifest(manifest_path, manifest)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["code_version"] = "tampered"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DomainViolation, match="hash"):
        read_manifest(manifest_path)


def test_public_collector_has_5m_15m_contract_and_no_auth_headers() -> None:
    url = build_public_url(
        "/fapi/v1/klines",
        {"symbol": "BTCUSDT", "interval": PRIMARY_INTERVAL, "limit": 3},
    )

    assert PRIMARY_INTERVAL == "5m"
    assert CONTEXT_INTERVAL == "15m"
    assert url.startswith("https://fapi.binance.com/fapi/v1/klines?")
    assert "apiKey" not in url
    assert "signature" not in url
    assert fully_closed_end_ms(10 * 60 * 60 * 1000 + 7 * 60 * 1000 + 12 * 1000, 300_000) == (
        10 * 60 * 60 * 1000 + 5 * 60 * 1000 - 1
    )
