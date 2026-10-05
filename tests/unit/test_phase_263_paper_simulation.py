"""Unit tests for Phase 263 multi-asset paper replay under Manifest Version 2."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
)
from scripts.run_phase_263_paper_simulation import (  # noqa: E402
    main,
    run_phase_263_simulation,
)


def test_legacy_veto_preserves_phase263_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "phase263_test"
    output_dir.mkdir()
    retained = (output_dir / "paper-ledger.sqlite3", output_dir / "paper-summary.json")
    for path in retained:
        path.write_bytes(b"retained-original-phase263-output")
    with pytest.raises(DataQualityError, match="bounded comparisons"):
        run_phase_263_simulation(output_dir=output_dir, days=1)
    for path in retained:
        assert path.read_bytes() == b"retained-original-phase263-output"


def test_historical_phase263_candidate_identity_contract() -> None:
    """Read-only original bindings, not current execution/qualification evidence."""
    manifest = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
    candidates = validate_manifest_candidate_artifacts(manifest)
    assert candidates["ETHUSDT"].candidate_id == "cand-ethusdt-dcb-003"
    assert candidates["BTCUSDT"].candidate_id == "cand-btcusdt-dcb-002"
    assert candidates["SOLUSDT"].candidate_id == "cand-solusdt-rgb-001"


def test_phase263_does_not_rebind_historical_eth_identity(
    tmp_path, synthetic_paper_registry
) -> None:
    with pytest.raises(DomainViolation, match="requires calibrated ETHUSDT candidate"):
        run_phase_263_simulation(
            output_dir=tmp_path / "distinct-synthetic-denied",
            registry_path=synthetic_paper_registry,
            days=1,
        )


def test_run_phase_263_simulation_rejects_manifest_v1(tmp_path: Path) -> None:
    # Point to the historical baseline registry (Version 1)
    baseline_reg = Path("artifacts/research/phase262/baseline_candidate_registry.json")
    if not baseline_reg.is_file():
        pytest.skip("baseline_candidate_registry.json not found")

    output_dir = tmp_path / "phase263_reject_test"
    with pytest.raises(DomainViolation, match="requires candidate registry version >= 2"):
        run_phase_263_simulation(
            output_dir=output_dir,
            registry_path=baseline_reg,
            days=1,
        )


def test_phase_263_cli_denies_unsupported_legacy_veto(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "cli_test"
    with pytest.raises(DataQualityError, match="bounded comparisons"):
        main(["--output-dir", str(output_dir), "--days", "1", "--json"])
    assert capsys.readouterr().out == ""
    assert not (output_dir / "paper-summary.json").exists()
