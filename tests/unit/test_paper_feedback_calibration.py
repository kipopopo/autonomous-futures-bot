"""Unit tests for Phase 262 Paper Trading Feedback Loop and Adaptive Calibration."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    build_candidate_registry_manifest,
    read_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    read_creator_candidate_artifact,
)
from scripts.run_paper_feedback_calibration import (  # noqa: E402
    extract_breach_feedback,
    main,
    run_paper_feedback_calibration,
    synthesize_calibrated_candidate,
)


def test_extract_breach_feedback_from_phase262_ledger() -> None:
    phase262_dir = Path("artifacts/research/phase262")
    ledger_path = phase262_dir / "paper-ledger.sqlite3"
    lifecycle_path = phase262_dir / "paper-lifecycle.sqlite3"
    phase262_baseline = phase262_dir / "baseline_candidate_registry.json"
    manifest_path = (
        phase262_baseline
        if phase262_baseline.is_file()
        else Path("artifacts/paper_live/candidate_registry.json")
    )
    manifest = read_candidate_registry(manifest_path)

    feedbacks = extract_breach_feedback(ledger_path, lifecycle_path, manifest)

    # Verify ETHUSDT is breached while BTC and SOL remain unbreached
    assert "ETHUSDT" in feedbacks
    fb_eth = feedbacks["ETHUSDT"]
    assert fb_eth.candidate_id == "cand-ethusdt-dcb-002"
    assert len(fb_eth.failed_gates) == 3

    failed_gate_ids = {g.gate_id for g in fb_eth.failed_gates}
    assert failed_gate_ids == {
        "paper_net_pnl_min",
        "paper_profit_factor_min",
        "paper_win_rate_min",
    }
    assert len(fb_eth.qualification_hash) == 64
    assert fb_eth.paper_activation is False
    assert fb_eth.exchange_access is False


def test_extract_breach_feedback_rejects_missing_candidate(tmp_path: Path) -> None:
    manifest = read_candidate_registry(
        Path("artifacts/research/phase262/baseline_candidate_registry.json")
    )
    missing = manifest.symbols["BTCUSDT"].model_copy(
        update={"artifact_path": str(tmp_path / "missing.json")}
    )
    manifest = build_candidate_registry_manifest(
        symbols={**manifest.symbols, "BTCUSDT": missing},
        registry_version=manifest.registry_version,
    )
    phase262 = Path("artifacts/research/phase262")
    with pytest.raises(FileNotFoundError, match="missing.json"):
        extract_breach_feedback(
            phase262 / "paper-ledger.sqlite3", phase262 / "paper-lifecycle.sqlite3", manifest
        )


def test_extract_breach_feedback_rejects_registry_artifact_mismatch() -> None:
    manifest = read_candidate_registry(
        Path("artifacts/research/phase262/baseline_candidate_registry.json")
    )
    wrong = manifest.symbols["BTCUSDT"].model_copy(update={"candidate_artifact_hash": "0" * 64})
    manifest = build_candidate_registry_manifest(
        symbols={**manifest.symbols, "BTCUSDT": wrong},
        registry_version=manifest.registry_version,
    )
    phase262 = Path("artifacts/research/phase262")
    with pytest.raises(DomainViolation, match="artifact hash mismatch"):
        extract_breach_feedback(
            phase262 / "paper-ledger.sqlite3", phase262 / "paper-lifecycle.sqlite3", manifest
        )


def test_synthesize_calibrated_candidate() -> None:
    base_cand = read_creator_candidate_artifact(
        Path("artifacts/paper_live/candidates/cand-ethusdt-dcb-002.json")
    )
    calibrated = synthesize_calibrated_candidate(base_cand, "cand-ethusdt-dcb-003")

    assert calibrated.candidate_id == "cand-ethusdt-dcb-003"
    assert calibrated.strategy.family == base_cand.strategy.family
    assert calibrated.strategy.universe.timeframe == "15m"
    assert calibrated.strategy.risk is not None
    assert calibrated.strategy.risk.stop_atr_multiplier == Decimal("1.5")
    assert calibrated.strategy.risk.trailing_atr_multiplier == Decimal("1.2")
    assert calibrated.strategy.risk.take_profit_atr_multiplier == Decimal("5.0")
    assert len(calibrated.artifact_hash) == 64


@pytest.mark.parametrize(
    "registry_path",
    [None, Path("artifacts/paper_live/candidate_registry.json").resolve()],
)
def test_calibration_does_not_reuse_baseline_qualification(
    tmp_path: Path, registry_path: Path | None
) -> None:
    out_dir = tmp_path / "calibration"
    with pytest.raises(ValueError, match="calibrated candidate requires its own qualification"):
        if registry_path is None:
            run_paper_feedback_calibration(output_dir=out_dir, days=1)
        else:
            run_paper_feedback_calibration(output_dir=out_dir, registry_path=registry_path, days=1)
    assert not out_dir.exists()


def test_calibration_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "cli_test"
    with pytest.raises(ValueError, match="calibrated candidate requires its own qualification"):
        main(["--output-dir", str(out_dir), "--days", "1", "--json"])
    assert not capsys.readouterr().out
