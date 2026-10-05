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


@pytest.fixture
def synthetic_multiasset_candidates():
    """Distinct canonical test-only inputs, never historical candidate replacements."""
    from tests.strategy_fixtures import synthetic_rsi_candidate

    return {
        symbol: synthetic_rsi_candidate(
            symbol=symbol,
            timeframe=timeframe,
            bundle_hash="a" * 64,
            dataset_registry_hash="b" * 64,
        )
        for symbol, timeframe in (("BTCUSDT", "15m"), ("ETHUSDT", "15m"), ("SOLUSDT", "1h"))
    }


@pytest.fixture
def synthetic_paper_registry(tmp_path, synthetic_multiasset_candidates):
    """Temporary typed synthetic registry; fake qualification hashes are test-only."""
    from autonomous_futures.paper.candidate_registry import (
        CandidateManifestEntry,
        build_candidate_registry_manifest,
        write_candidate_registry,
    )
    from autonomous_futures.research.creator_artifacts import write_creator_candidate_artifact

    entries = {}
    for symbol, candidate in synthetic_multiasset_candidates.items():
        path = tmp_path / f"{candidate.candidate_id}.json"
        write_creator_candidate_artifact(path, candidate)
        entries[symbol] = CandidateManifestEntry(
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            artifact_path=str(path),
            qualification_hash="c" * 64,
            admitted_at="2026-01-01T00:00:00+00:00",
        )
    manifest = build_candidate_registry_manifest(
        symbols=entries,
        updated_at="2026-01-01T00:00:00+00:00",
        registry_version=2,
    )
    path = tmp_path / "synthetic-registry.json"
    write_candidate_registry(path, manifest)
    return path


@pytest.fixture
def synthetic_phase251_inputs(tmp_path, monkeypatch, request):
    """Fresh test-only paper inputs; original files and stored pins stay untouched."""
    from datetime import UTC, datetime
    from decimal import Decimal
    from functools import partial

    import scripts.run_phase_251_paper_simulation as cli
    from autonomous_futures.research.creator_artifacts import write_creator_candidate_artifact
    from autonomous_futures.research.qualification_artifacts import (
        QualificationGateResult,
        QualificationMetric,
        build_creator_candidate_qualification_artifact,
        write_creator_candidate_qualification_artifact,
    )
    from tests.strategy_fixtures import synthetic_rsi_candidate

    candidate = synthetic_rsi_candidate(
        symbol="DOGEUSDT",
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        vetoes=getattr(request, "param", ("rsi > 0 and rsi < 0",)),
    )
    qualification = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="synthetic-paper-accounting",
        evaluator_version="1",
        decision="qualified",
        windows_evaluated=1,
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        metrics=(QualificationMetric(metric_id="synthetic", value=Decimal("1")),),
        gates=(
            QualificationGateResult(
                gate_id="synthetic",
                passed=True,
                comparator="bool",
                reason_code="synthetic_fixture",
            ),
        ),
    )
    candidate_path = tmp_path / "synthetic-candidate.json"
    qualification_path = tmp_path / "synthetic-qualification.json"
    write_creator_candidate_artifact(candidate_path, candidate)
    write_creator_candidate_qualification_artifact(qualification_path, qualification)
    monkeypatch.setattr(cli, "PINNED_CANDIDATE_ID", candidate.candidate_id)
    monkeypatch.setattr(cli, "PINNED_ARTIFACT_HASH", candidate.artifact_hash)
    monkeypatch.setattr(cli, "PINNED_QUALIFICATION_HASH", qualification.qualification_hash)
    monkeypatch.setattr(
        request.module,
        "run_paper_simulation",
        partial(
            cli.run_paper_simulation,
            candidate_path=candidate_path,
            qualification_path=qualification_path,
        ),
    )
    return candidate
