from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest


@pytest.fixture
def verified_cycle_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Path:
    """Primary-only cached fixture; no complete market/source-authority claim."""
    import scripts.run_autonomous_cycle as cli
    from autonomous_futures.data.parquet import read_canonical_parquet, write_canonical_parquet
    from tests.data_fixtures import write_primary_cached_catalog

    source = (
        Path(__file__).resolve().parents[1]
        / "research/immutable-data/5m/canonical/BTCUSDT-5m.parquet"
    )
    frame = read_canonical_parquet(source, interval=timedelta(minutes=5)).iloc[-864:].copy()
    root = tmp_path / "data"
    parquet = root / "5m/canonical/BTCUSDT-5m.parquet"
    write_canonical_parquet(frame, parquet, interval=timedelta(minutes=5))
    catalog = write_primary_cached_catalog(parquet, root)

    original_parser = cli.build_parser

    def fixture_parser():
        parser = original_parser()
        parser.set_defaults(
            dataset_root=root,
            bundle_hash=catalog.bundle.bundle_hash,
            dataset_registry_hash=catalog.registry.registry_hash,
        )
        return parser

    monkeypatch.setattr(cli, "build_parser", fixture_parser)
    for name in ("PARQUET_PATH", "CANONICAL_PARQUET"):
        if hasattr(request.module, name):
            monkeypatch.setattr(request.module, name, parquet)
    for name in ("BUNDLE_HASH", "HASH_A"):
        if hasattr(request.module, name):
            monkeypatch.setattr(request.module, name, catalog.bundle.bundle_hash)
    for name in ("REGISTRY_HASH", "HASH_B"):
        if hasattr(request.module, name):
            monkeypatch.setattr(request.module, name, catalog.registry.registry_hash)
    return root
