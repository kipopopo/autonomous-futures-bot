"""Unit tests for Phase 251: Offline Paper Trading Simulation Harness.

Verifies:
- Candidate ID 69-character regex support in PaperExecutionRequest and PaperLedgerEntry.
- Artifact loading from Phase 250 (candidate & qualification).
- Isolated SQLite stores creation and persistence.
- Deterministic paper simulation loop execution, adverse fills, and fee deduction.
- Reconciled accounting: net_pnl == gross_pnl - entry_fee - exit_fee, cash balance reconciliation.
- Position reconciliation via reconcile_paper_positions.
- PaperHealthReport and PaperCohortReadinessReport generation.
- Strict offline safety invariants: exchange_access=False, orders=0, paper_activation=False.
- Edge cases: missing approval, expired approval, duplicate open attempt, invalid symbol.
- Standalone CLI execution.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import PaperExecutionRequest
from autonomous_futures.paper.ledger import (
    PaperLedgerEntry,
    PaperLedgerError,
)
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.observation import observe_paper_ledger
from autonomous_futures.paper.reconciliation import reconcile_paper_positions
from autonomous_futures.paper.runtime import PaperRuntime
from autonomous_futures.paper.safety import (
    PaperActionApproval,
    PaperSafetyEvidence,
)
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations
from autonomous_futures.research.creator_artifacts import (
    read_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (
    read_creator_candidate_qualification_artifact,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_251_paper_simulation import (  # noqa: E402
    _SECRET_PATTERN,
    PINNED_ARTIFACT_HASH,
    PINNED_BUNDLE_HASH,
    PINNED_CANDIDATE_ID,
    PINNED_QUALIFICATION_HASH,
    PINNED_REGISTRY_HASH,
    compute_file_sha256,
    main,
    run_paper_simulation,
)

CANONICAL_69_CHAR_ID = "cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"


# ---------------------------------------------------------------------------
# 1. Candidate ID Regex Alignment Tests
# ---------------------------------------------------------------------------


def test_paper_execution_request_accepts_canonical_69_char_candidate_id() -> None:
    assert len(CANONICAL_69_CHAR_ID) == 69
    request = PaperExecutionRequest(
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        qualified_symbols=("DOGEUSDT",),
        symbol="DOGEUSDT",
        side="LONG",
        mark_price=Decimal("0.15"),
        quantity=Decimal("1000.0"),
        fee_rate=Decimal("0.0004"),
        slippage_bps=Decimal("2"),
    )
    assert request.candidate_id == CANONICAL_69_CHAR_ID
    assert request.activation_state == "blocked"
    assert request.paper_activation is False
    assert request.execution_authority is False
    assert request.exchange_access is False


def test_paper_execution_request_accepts_short_id_and_rejects_invalid_pattern() -> None:
    # Short valid IDs still pass
    request = PaperExecutionRequest(
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        qualified_symbols=("DOGEUSDT",),
        symbol="DOGEUSDT",
        side="LONG",
        mark_price=Decimal("0.15"),
        quantity=Decimal("1000.0"),
        fee_rate=Decimal("0.0004"),
        slippage_bps=Decimal("2"),
    )
    assert request.candidate_id == "cand-scope-rsi-adx-001"

    # Uppercase in candidate_id rejected
    with pytest.raises(ValidationError):
        PaperExecutionRequest(
            candidate_id="CAND-UPPERCASE",
            candidate_artifact_hash="a" * 64,
            qualified_symbols=("DOGEUSDT",),
            symbol="DOGEUSDT",
            side="LONG",
            mark_price=Decimal("0.15"),
            quantity=Decimal("1000.0"),
            fee_rate=Decimal("0.0004"),
            slippage_bps=Decimal("2"),
        )

    # Empty candidate_id rejected
    with pytest.raises(ValidationError):
        PaperExecutionRequest(
            candidate_id="",
            candidate_artifact_hash="a" * 64,
            qualified_symbols=("DOGEUSDT",),
            symbol="DOGEUSDT",
            side="LONG",
            mark_price=Decimal("0.15"),
            quantity=Decimal("1000.0"),
            fee_rate=Decimal("0.0004"),
            slippage_bps=Decimal("2"),
        )


def test_paper_ledger_entry_accepts_canonical_69_char_candidate_id() -> None:
    entry = PaperLedgerEntry(
        event="open",
        trade_id="trade-001",
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        symbol="DOGEUSDT",
        side="LONG",
        quantity=Decimal("1000.0"),
        fill_price=Decimal("0.15003"),
        occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
        entry_fee=Decimal("0.06"),
        slippage_cost=Decimal("0.03"),
    )
    assert entry.candidate_id == CANONICAL_69_CHAR_ID

    # Reject invalid characters
    with pytest.raises(ValidationError):
        PaperLedgerEntry(
            event="open",
            trade_id="trade-001",
            candidate_id="cand with spaces!",
            candidate_artifact_hash="a" * 64,
            symbol="DOGEUSDT",
            side="LONG",
            quantity=Decimal("1000.0"),
            fill_price=Decimal("0.15"),
            occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
            entry_fee=Decimal("0.06"),
            slippage_cost=Decimal("0.03"),
        )


# ---------------------------------------------------------------------------
# 2. Phase 250 Artifacts Loading and Integrity
# ---------------------------------------------------------------------------


def test_phase_250_artifacts_loading_and_integrity() -> None:
    candidate_path = Path("artifacts/research/phase250/candidate-artifact.json")
    qualification_path = Path("artifacts/research/phase250/qualification-artifact.json")

    candidate = read_creator_candidate_artifact(candidate_path)
    qualification = read_creator_candidate_qualification_artifact(qualification_path)

    assert candidate.candidate_id == PINNED_CANDIDATE_ID
    assert candidate.artifact_hash == PINNED_ARTIFACT_HASH
    assert candidate.bundle_hash == PINNED_BUNDLE_HASH
    assert candidate.dataset_registry_hash == PINNED_REGISTRY_HASH
    assert candidate.strategy.universe.symbols == ("DOGEUSDT",)
    assert candidate.strategy.universe.timeframe == "5m"
    assert candidate.strategy.family == "range_mean_reversion"

    assert qualification.decision == "qualified"
    assert qualification.candidate_id == PINNED_CANDIDATE_ID
    assert qualification.candidate_artifact_hash == PINNED_ARTIFACT_HASH
    assert qualification.qualification_hash == PINNED_QUALIFICATION_HASH
    assert qualification.execution_authority is False
    assert qualification.promotion_state == "unpromoted"


# ---------------------------------------------------------------------------
# 3. Isolated SQLite Stores Creation and Persistence
# ---------------------------------------------------------------------------


def test_isolated_sqlite_stores_creation_and_persistence(tmp_path: Path) -> None:
    ledger_db = tmp_path / "test-ledger.sqlite3"
    lifecycle_db = tmp_path / "test-lifecycle.sqlite3"
    observation_db = tmp_path / "test-observations.sqlite3"

    assert not ledger_db.exists()
    assert not lifecycle_db.exists()
    assert not observation_db.exists()

    ledger = SqlitePaperLedger(ledger_db)
    lifecycle = SqlitePaperLifecycle(lifecycle_db)
    observations = SqlitePaperObservations(observation_db)

    # Empty read on absent path does not create file
    assert ledger.load().entries == ()
    assert not ledger_db.exists()
    assert lifecycle.read(candidate_id="c1", candidate_artifact_hash="a" * 64, trade_id="t1") == ()
    assert not lifecycle_db.exists()
    assert observations.read("c1", "a" * 64) == ()
    assert not observation_db.exists()

    # Append into ledger
    entry = PaperLedgerEntry(
        event="open",
        trade_id="t1",
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        symbol="DOGEUSDT",
        side="LONG",
        quantity=Decimal("100.0"),
        fill_price=Decimal("0.15"),
        occurred_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        entry_fee=Decimal("0.006"),
        slippage_cost=Decimal("0.003"),
    )
    ledger.append(entry)
    assert ledger_db.exists()
    loaded_ledger = ledger.load()
    assert len(loaded_ledger.entries) == 1
    assert loaded_ledger.entries[0].trade_id == "t1"

    # Append into lifecycle
    telemetry = mark_paper_position(
        entry,
        mark_price=Decimal("0.16"),
        marked_at=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        previous_peak_pnl=Decimal("0"),
    )
    lifecycle.append(telemetry)
    assert lifecycle_db.exists()
    marks = lifecycle.read_candidate(
        candidate_id=CANONICAL_69_CHAR_ID, candidate_artifact_hash="a" * 64
    )
    assert len(marks) == 1
    assert marks[0].trade_id == "t1"
    assert marks[0].mark_price == Decimal("0.16")

    # Append into observations
    obs = observe_paper_ledger(
        loaded_ledger,
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        starting_equity=Decimal("10000.00"),
        previous_peak_equity=Decimal("10000.00"),
        mark_prices={"DOGEUSDT": Decimal("0.16")},
        observed_at=datetime(2026, 1, 1, 6, 0, tzinfo=UTC),
    )
    observations.append(obs)
    assert observation_db.exists()
    obs_list = observations.read(CANONICAL_69_CHAR_ID, "a" * 64)
    assert len(obs_list) == 1
    assert obs_list[0].open_position_count == 1


# ---------------------------------------------------------------------------
# 4. Deterministic Simulation Loop Execution
# ---------------------------------------------------------------------------


def test_deterministic_simulation_loop_execution(tmp_path: Path) -> None:
    output_dir = tmp_path / "paper_phase251"
    result = run_paper_simulation(
        output_dir=output_dir,
        days=7,
        starting_equity=Decimal("10000.00"),
        quantity=Decimal("1000.0"),
        fee_rate=Decimal("0.0004"),
        slippage_bps=Decimal("2"),
    )

    # Candidate binding
    assert result.candidate_id == PINNED_CANDIDATE_ID
    assert result.candidate_artifact_hash == PINNED_ARTIFACT_HASH

    # Execution metrics
    assert result.total_bars == 2017
    assert result.total_trades > 0
    assert result.winning_trades > 0
    assert result.win_rate > 0.5
    assert result.realized_pnl > Decimal("0")
    assert result.final_cash > Decimal("10000.00")
    assert result.cumulative_fees > Decimal("0")
    assert result.cumulative_slippage > Decimal("0")

    # Reconciliations
    assert result.positions_reconciled is True
    assert result.accounting_reconciled is True

    # Reports
    assert result.health_report.health_status == "healthy"
    assert result.health_report.maturity_status == "mature"
    assert result.cohort_report.cohort_status == "ready_for_human_review"

    # Artifact generation and hashing
    expected_files = [
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
        "paper-health-report.json",
        "paper-cohort-readiness-report.json",
        "paper-simulation-summary.json",
    ]
    for filename in expected_files:
        path = output_dir / filename
        assert path.is_file(), f"Missing expected artifact: {filename}"
        assert compute_file_sha256(path) == result.artifact_hashes[filename], (
            f"Hash mismatch for {filename}"
        )


# ---------------------------------------------------------------------------
# 5. Reconciled Accounting & Cash Balances
# ---------------------------------------------------------------------------


def test_accounting_balance_reconciliation(tmp_path: Path) -> None:
    output_dir = tmp_path / "accounting_test"
    result = run_paper_simulation(
        output_dir=output_dir,
        days=7,
        starting_equity=Decimal("5000.00"),
        quantity=Decimal("1000.0"),
    )

    ledger_db = output_dir / "paper-ledger.sqlite3"
    ledger = SqlitePaperLedger(ledger_db).load()

    closed_entries = [e for e in ledger.entries if e.event == "close"]
    open_entries = [e for e in ledger.entries if e.event == "open"]
    assert len(closed_entries) == len(open_entries)

    total_realized_pnl = Decimal("0")
    for trade in closed_entries:
        assert trade.gross_pnl is not None
        assert trade.entry_fee is not None
        assert trade.exit_fee is not None
        assert trade.net_pnl is not None
        assert trade.slippage_cost is not None

        # Net PnL must strictly equal gross PnL minus entry and exit fees
        expected_net = trade.gross_pnl - trade.entry_fee - trade.exit_fee
        assert trade.net_pnl == expected_net
        total_realized_pnl += trade.net_pnl

    expected_cash = Decimal("5000.00") + total_realized_pnl
    assert result.final_cash == expected_cash
    assert result.realized_pnl == total_realized_pnl


# ---------------------------------------------------------------------------
# 6. Position Reconciliation via reconcile_paper_positions
# ---------------------------------------------------------------------------


def test_reconcile_paper_positions_zero_drift(tmp_path: Path) -> None:
    output_dir = tmp_path / "recon_test"
    run_paper_simulation(output_dir=output_dir, days=7)

    ledger = SqlitePaperLedger(output_dir / "paper-ledger.sqlite3").load()
    reconciliation = reconcile_paper_positions(ledger, ())

    assert reconciliation.reconciled is True
    assert reconciliation.runtime_only_trade_ids == ()
    assert reconciliation.ledger_only_trade_ids == ()
    assert reconciliation.reason_codes == ("paper_positions_reconciled",)

    # Verify drift detection if runtime claims a phantom position
    drift_result = reconcile_paper_positions(ledger, ("phantom-trade-999",))
    assert drift_result.reconciled is False
    assert "runtime_position_missing_from_ledger" in drift_result.reason_codes
    assert drift_result.runtime_only_trade_ids == ("phantom-trade-999",)


# ---------------------------------------------------------------------------
# 7. Paper Health & Cohort Readiness Models
# ---------------------------------------------------------------------------


def test_paper_health_and_cohort_readiness_reporting(tmp_path: Path) -> None:
    output_dir = tmp_path / "health_cohort_test"
    run_paper_simulation(output_dir=output_dir, days=7)

    health_path = output_dir / "paper-health-report.json"
    cohort_path = output_dir / "paper-cohort-readiness-report.json"

    health_data = json.loads(health_path.read_text(encoding="utf-8"))
    cohort_data = json.loads(cohort_path.read_text(encoding="utf-8"))

    assert health_data["candidate_id"] == PINNED_CANDIDATE_ID
    assert health_data["health_status"] == "healthy"
    assert health_data["maturity_status"] == "mature"
    assert health_data["accounting_complete"] is True
    assert health_data["open_position_count"] == 0
    assert health_data["paper_activation"] is False
    assert health_data["execution_authority"] is False
    assert health_data["exchange_access"] is False

    assert cohort_data["cohort_status"] == "ready_for_human_review"
    assert cohort_data["all_mature"] is True
    assert cohort_data["all_accounting_complete"] is True
    assert cohort_data["expected_candidate_count"] == 1
    assert cohort_data["reported_candidate_count"] == 1
    assert cohort_data["healthy_candidate_count"] == 1
    assert cohort_data["mature_candidate_count"] == 1
    assert cohort_data["blocked_candidate_count"] == 0
    assert cohort_data["attention_candidate_count"] == 0
    assert cohort_data["paper_activation"] is False
    assert cohort_data["execution_authority"] is False
    assert cohort_data["exchange_access"] is False


# ---------------------------------------------------------------------------
# 8. Offline Safety Invariants & Zero Secret Leakage
# ---------------------------------------------------------------------------


def test_offline_safety_invariants_and_zero_secret_leakage(tmp_path: Path) -> None:
    output_dir = tmp_path / "safety_test"
    run_paper_simulation(output_dir=output_dir, days=7)

    summary_path = output_dir / "paper-simulation-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    # Invariants in summary payload
    safety = summary["safety_invariants"]
    assert safety["orders"] == 0
    assert safety["exchange_access"] is False
    assert safety["execution_authority"] is False
    assert safety["promotion_state"] == "unpromoted"
    assert safety["paper_activation"] is False
    assert safety["data_source"] == "cached_only"
    assert safety["zero_secret_leakage"] is True

    # Scan all generated text and JSON files in output_dir for secrets
    for f in output_dir.iterdir():
        if f.suffix in (".json", ".txt"):
            content = f.read_text(encoding="utf-8")
            assert not _SECRET_PATTERN.search(content), f"Secret pattern matched in {f.name}"


# ---------------------------------------------------------------------------
# 9. Edge Cases: Approvals, Duplicates, and Validation
# ---------------------------------------------------------------------------


def test_simulation_edge_cases_expired_and_mismatched_approval(
    tmp_path: Path,
) -> None:
    ledger_db = tmp_path / "edge-ledger.sqlite3"
    ledger = SqlitePaperLedger(ledger_db)
    runtime = PaperRuntime(ledger)

    req = PaperExecutionRequest(
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        qualified_symbols=("DOGEUSDT",),
        symbol="DOGEUSDT",
        side="LONG",
        mark_price=Decimal("0.15"),
        quantity=Decimal("1000.0"),
        fee_rate=Decimal("0.0004"),
        slippage_bps=Decimal("2"),
    )
    evidence = PaperSafetyEvidence(
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        qualification_hash="b" * 64,
        qualification_decision="qualified",
        zero_oos_liquidations=True,
    )

    bar_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    # 1. Expired approval
    expired_approval = PaperActionApproval(
        approval_id="apprv-expired-001",
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        trade_id="trade-001",
        action="open",
        approved_at=bar_time - timedelta(minutes=10),
        expires_at=bar_time - timedelta(minutes=5),
    )
    res = runtime.open(req, evidence, expired_approval, trade_id="trade-001", occurred_at=bar_time)
    assert res.status == "blocked"
    assert "approval_expired" in res.reason_codes

    # 2. Action mismatch approval (close approval supplied for open action)
    mismatched_approval = PaperActionApproval(
        approval_id="apprv-mismatch-001",
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        trade_id="trade-001",
        action="close",
        approved_at=bar_time,
        expires_at=bar_time + timedelta(minutes=5),
    )
    res = runtime.open(
        req, evidence, mismatched_approval, trade_id="trade-001", occurred_at=bar_time
    )
    assert res.status == "blocked"
    assert "approval_action_mismatch" in res.reason_codes


def test_simulation_edge_cases_duplicate_open_and_unqualified_symbol(
    tmp_path: Path,
) -> None:
    ledger_db = tmp_path / "dup-ledger.sqlite3"
    ledger = SqlitePaperLedger(ledger_db)

    open_entry = PaperLedgerEntry(
        event="open",
        trade_id="trade-001",
        candidate_id=CANONICAL_69_CHAR_ID,
        candidate_artifact_hash="a" * 64,
        symbol="DOGEUSDT",
        side="LONG",
        quantity=Decimal("1000.0"),
        fill_price=Decimal("0.15"),
        occurred_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        entry_fee=Decimal("0.06"),
        slippage_cost=Decimal("0.03"),
    )
    ledger.append(open_entry)

    # Duplicate open for the same candidate and symbol raises PaperLedgerError
    duplicate_open = open_entry.model_copy(update={"trade_id": "trade-002"})
    with pytest.raises(PaperLedgerError, match="duplicate open"):
        ledger.append(duplicate_open)

    # Symbol outside qualified symbols raises ValidationError
    with pytest.raises(ValidationError, match="qualified universe"):
        PaperExecutionRequest(
            candidate_id=CANONICAL_69_CHAR_ID,
            candidate_artifact_hash="a" * 64,
            qualified_symbols=("DOGEUSDT",),
            symbol="BTCUSDT",
            side="LONG",
            mark_price=Decimal("100.0"),
            quantity=Decimal("1.0"),
            fee_rate=Decimal("0.0004"),
            slippage_bps=Decimal("2"),
        )


# ---------------------------------------------------------------------------
# 10. CLI Execution Tests
# ---------------------------------------------------------------------------


def test_cli_main_execution(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli_test_out"
    exit_code = main(
        [
            "--output-dir",
            str(output_dir),
            "--days",
            "7",
            "--starting-equity",
            "10000.00",
            "--quantity",
            "1000.0",
        ]
    )
    assert exit_code == 0
    assert (output_dir / "paper-simulation-summary.json").is_file()
    assert (output_dir / "paper-health-report.json").is_file()
    assert (output_dir / "paper-cohort-readiness-report.json").is_file()
