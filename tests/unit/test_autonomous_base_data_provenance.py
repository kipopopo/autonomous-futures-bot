from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError, write_canonical_parquet

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_autonomous_base import load_and_slice_windows  # noqa: E402


def test_parquet_is_bound_to_bundle_component_and_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet_path = tmp_path / "BTCUSDT-5m.parquet"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(4)],
            "open": [100, 101, 102, 103],
            "high": [101, 102, 103, 104],
            "low": [99, 100, 101, 102],
            "close": [100, 101, 102, 103],
        }
    )
    write_canonical_parquet(frame, parquet_path, interval=timedelta(minutes=5))
    before = sha256(parquet_path.read_bytes()).hexdigest()

    import autonomous_futures.api.artifacts as artifact_api

    monkeypatch.setattr(
        artifact_api,
        "load_verified_dataset_catalog",
        lambda **_: SimpleNamespace(
            bundle=SimpleNamespace(bundle_hash="1" * 64),
            registry=SimpleNamespace(registry_hash="2" * 64),
        ),
    )
    monkeypatch.setattr(artifact_api, "find_bundle_component", lambda *_, **__: object())
    monkeypatch.setattr(
        artifact_api,
        "inspect_artifact_entry",
        lambda *_: SimpleNamespace(data_ref="different.parquet"),
    )
    with pytest.raises(DataQualityError, match="bundle dataset artifact provenance"):
        load_and_slice_windows(
            parquet_path,
            symbol="BTCUSDT",
            bundle_hash="1" * 64,
            dataset_registry_hash="2" * 64,
            dataset_root=tmp_path,
            bundle_path=tmp_path / "bundle.json",
            registry_path=tmp_path / "registry.json",
            windows_count=1,
            bars_per_window=4,
        )

    assert before == sha256(parquet_path.read_bytes()).hexdigest()


def test_normal_cycle_rejects_parquet_without_verified_catalog(tmp_path: Path) -> None:
    from scripts.run_autonomous_cycle import load_and_slice_windows as load_cycle_windows

    parquet_path = tmp_path / "BTCUSDT-5m.parquet"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(4)],
            "open": [100, 101, 102, 103],
            "high": [101, 102, 103, 104],
            "low": [99, 100, 101, 102],
            "close": [100, 101, 102, 103],
        }
    )
    write_canonical_parquet(frame, parquet_path, interval=timedelta(minutes=5))
    with pytest.raises(ValueError):
        load_cycle_windows(
            parquet_path,
            symbol="BTCUSDT",
            bundle_hash="1" * 64,
            dataset_registry_hash="2" * 64,
            windows_count=1,
            bars_per_window=4,
        )


def test_normal_cycle_accepts_explicit_catalog_paths(tmp_path: Path) -> None:
    from scripts.run_autonomous_cycle import build_parser

    args = build_parser().parse_args(
        [
            "--symbol",
            "BTCUSDT",
            "--dataset-root",
            str(tmp_path),
            "--bundle-path",
            str(tmp_path / "bundle.json"),
            "--registry-path",
            str(tmp_path / "registry.json"),
        ]
    )
    assert args.dataset_root == tmp_path
    assert args.bundle_path == tmp_path / "bundle.json"
    assert args.registry_path == tmp_path / "registry.json"
