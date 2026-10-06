from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from autonomous_futures.data.parquet import write_canonical_parquet
from tests.data_fixtures import write_primary_cached_catalog

START = datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
END = START + timedelta(minutes=150)
SYMBOL = "BTCUSDT"


def _write_complete_catalog(root: Path) -> tuple[Path, Path, Path, str, str]:
    parquet = root / "5m/canonical/BTCUSDT-5m.parquet"
    timestamps = tuple(START + timedelta(minutes=5 * index) for index in range(30))
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal("100") + index for index in range(30)],
            "high": [Decimal("101") + index for index in range(30)],
            "low": [Decimal("99") + index for index in range(30)],
            "close": [Decimal("100") + index for index in range(30)],
        }
    )
    write_canonical_parquet(frame, parquet, interval=timedelta(minutes=5))
    catalog = write_primary_cached_catalog(parquet, root)
    return (
        root,
        root / "bundle.json",
        root / "registry.json",
        catalog.bundle.bundle_hash,
        catalog.registry.registry_hash,
    )


def test_real_bundle_to_cached_window_binds_kline_and_funding_bytes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.evaluate_phase_250_walk_forward import load_verified_oos_windows
    from scripts.explore_offline_strategies import (
        load_and_slice_windows as load_exploration_windows,
    )
    from scripts.run_autonomous_cycle import load_and_slice_windows

    root, bundle_path, registry_path, bundle_hash, registry_hash = _write_complete_catalog(
        tmp_path / "dataset"
    )
    parquet_path = root / f"5m/canonical/{SYMBOL}-5m.parquet"
    windows = load_and_slice_windows(
        parquet_path,
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        windows_count=1,
        bars_per_window=3,
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    window = windows[0]

    assert window.spec.bundle_hash == bundle_hash
    assert window.spec.dataset_registry_hash == registry_hash
    assert window.spec.funding_artifact_hash is not None
    assert window.funding_slice is not None
    assert window.funding_slice.bundle_hash == bundle_hash
    assert window.funding_slice.dataset_registry_hash == registry_hash
    assert tuple(window.copy_funding_events()["funding_time"]) == (
        pd.Timestamp(END - timedelta(minutes=10)),
        pd.Timestamp(END - timedelta(minutes=5)),
    )

    phase250_windows = load_verified_oos_windows(
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        count=1,
        bars_per_window=30,
        start=START,
        data_dir=root / "5m/canonical",
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    assert len(phase250_windows) == 1
    assert phase250_windows[0].frame.shape[0] == 30
    assert phase250_windows[0].funding_slice is not None
    assert phase250_windows[0].spec.funding_artifact_hash is not None

    exploration_windows = load_exploration_windows(
        parquet_path,
        symbol=SYMBOL,
        bundle_hash=bundle_hash,
        dataset_registry_hash=registry_hash,
        windows_count=1,
        bars_per_window=30,
        dataset_root=root,
        bundle_path=bundle_path,
        registry_path=registry_path,
    )
    assert len(exploration_windows) == 1
    assert exploration_windows[0].funding_slice is not None
