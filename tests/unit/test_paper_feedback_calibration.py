"""Unit tests for Phase 262 Paper Trading Feedback Loop and Adaptive Calibration."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomous_futures.paper.candidate_registry import read_candidate_registry  # noqa: E402
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


def test_run_paper_feedback_calibration_short_slice(tmp_path: Path) -> None:
    out_dir = tmp_path / "calibration_test"
    result = run_paper_feedback_calibration(
        output_dir=out_dir,
        days=1,
    )

    assert result.summary_path.is_file()
    assert (out_dir / "calibrated_candidate_registry.json").is_file()
    assert (out_dir / "feedback" / "feedback-cand-ethusdt-dcb-002.json").is_file()
    assert (out_dir / "feedback" / "cand-ethusdt-dcb-003.json").is_file()
    assert "cand-ethusdt-dcb-002" in result.forbidden_candidate_ids

    # Read summary and check payload
    summary_data = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary_data["phase"] == "phase_262_feedback_calibration"
    assert "ETHUSDT" in summary_data["breached_candidates"]
    assert "baseline" in summary_data["comparison"]
    assert "calibrated" in summary_data["comparison"]
    assert "fee_savings_usdt" in summary_data["comparison"]

    # Invariants
    assert summary_data["safety_invariants"]["exchange_access"] is False
    assert summary_data["safety_invariants"]["paper_activation"] is False


def test_calibration_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "cli_test"
    code = main(["--output-dir", str(out_dir), "--days", "1", "--json"])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["phase"] == "phase_262_feedback_calibration"
    assert "cand-ethusdt-dcb-002" in data["forbidden_candidate_ids"]
