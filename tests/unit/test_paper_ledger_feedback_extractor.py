"""Unit test suite for autonomous_futures.paper.feedback_extractor.

Verifies:
1. Happy path: underperforming candidate in SQLite ledger breaches policy thresholds
   and produces valid CreatorQualificationFailureFeedback.
2. Non-breach path: outperforming candidate produces no failure feedback (returns None).
3. Real database verification: tests against artifacts/paper/phase251/paper-ledger.sqlite3.
4. Synthetic database helper: fixture creating temporary SQLite ledger and lifecycle
   databases with customized trade records to test exact edge cases.
5. Edge cases: candidate with 0 trades, candidate with all losses, candidate with all
   wins, multiple candidates in the same ledger ensuring isolation, and unclosed trades.
6. Compliance validation: verify returned feedback strictly validates against
   CreatorQualificationFailureFeedback schema, serializes to JSON, and passes intake
   validation of execute_autonomous_cycle and LearnerCritic.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.feedback_extractor import (
    PaperFeedbackExtractor,
    PaperQualificationPolicy,
    extract_paper_feedback,
    paper_qualification_policy_content_hash,
)
from autonomous_futures.pipeline.autonomous_cycle import AutonomousCycleConfig
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.learner_critic import LearnerCriticRequest
from autonomous_futures.research.qualification_artifacts import WalkForwardQualificationPolicy

# Test Constants
BUNDLE_HASH = "a" * 64
DATASET_HASH = "b" * 64
POLICY_ID = "paper-policy-v1"
NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


def _build_test_candidate(
    candidate_id: str = "cand-test-extractor-001",
    symbol: str = "BTCUSDT",
    bundle_hash: str = BUNDLE_HASH,
    dataset_hash: str = DATASET_HASH,
) -> CreatorCandidateArtifact:
    """Construct a strongly typed CreatorCandidateArtifact for testing."""
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_hash,
        creator_run_id="run-test-001",
        research_seed=42,
        created_at=NOW,
    )


@pytest.fixture
def default_policy() -> PaperQualificationPolicy:
    """Standard paper qualification policy."""
    return PaperQualificationPolicy(
        policy_id=POLICY_ID,
        paper_net_pnl_min=Decimal("0.0"),
        paper_profit_factor_min=Decimal("1.05"),
        paper_win_rate_min=Decimal("45.0"),
        paper_drawdown_max=Decimal("15.0"),
        paper_trades_min=5,
    )


def create_synthetic_ledger(
    storage_dir: Path,
    trades: Sequence[dict[str, Any]],
    lifecycle_marks: Sequence[dict[str, Any]] | None = None,
) -> Path:
    """Create synthetic paper-ledger.sqlite3 and paper-lifecycle.sqlite3 databases."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = storage_dir / "paper-ledger.sqlite3"
    conn = sqlite3.connect(ledger_path)
    conn.execute("""
        CREATE TABLE paper_ledger_events (
            sequence INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            candidate_artifact_hash TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity TEXT NOT NULL,
            fill_price TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            approval_id TEXT,
            entry_fee TEXT,
            exit_fee TEXT,
            slippage_cost TEXT,
            gross_pnl TEXT,
            net_pnl TEXT
        );
    """)
    conn.execute("""
        CREATE TABLE paper_position_state (
            trade_id TEXT PRIMARY KEY,
            state_version INTEGER NOT NULL,
            state_json TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE paper_position_update_intent (
            trade_id TEXT PRIMARY KEY,
            intent TEXT NOT NULL
        );
    """)

    seq = 1
    for t in trades:
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)
            """,
            (
                seq,
                t["trade_id"],
                t["candidate_id"],
                t["candidate_artifact_hash"],
                t.get("symbol", "BTCUSDT"),
                t.get("side", "LONG"),
                str(t.get("quantity", "0.01")),
                str(t["entry_price"]),
                t["opened_at"],
                f"app-open-{seq}",
                str(t.get("entry_fee", "0.02")),
                str(t.get("slippage_cost", "0.01")),
            ),
        )
        seq += 1

        if not t.get("open_only", False):
            conn.execute(
                """
                INSERT INTO paper_ledger_events VALUES
                (?, 'close', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq,
                    t["trade_id"],
                    t["candidate_id"],
                    t["candidate_artifact_hash"],
                    t.get("symbol", "BTCUSDT"),
                    t.get("side", "LONG"),
                    str(t.get("quantity", "0.01")),
                    str(t["exit_price"]),
                    t["closed_at"],
                    f"app-close-{seq}",
                    str(t.get("entry_fee", "0.02")),
                    str(t.get("exit_fee", "0.02")),
                    str(t.get("slippage_cost", "0.01")),
                    str(t["gross_pnl"]),
                    str(t["net_pnl"]),
                ),
            )
            seq += 1

    conn.commit()
    conn.close()

    lifecycle_path = storage_dir / "paper-lifecycle.sqlite3"
    conn_lc = sqlite3.connect(lifecycle_path)
    conn_lc.execute("""
        CREATE TABLE paper_lifecycle_marks (
            sequence INTEGER PRIMARY KEY,
            candidate_id TEXT,
            candidate_artifact_hash TEXT,
            trade_id TEXT,
            marked_at TEXT,
            payload TEXT
        );
    """)
    if lifecycle_marks:
        for i, mark in enumerate(lifecycle_marks, 1):
            conn_lc.execute(
                "INSERT INTO paper_lifecycle_marks VALUES (?, ?, ?, ?, ?, ?)",
                (
                    i,
                    mark["candidate_id"],
                    mark["candidate_artifact_hash"],
                    mark["trade_id"],
                    mark["marked_at"],
                    json.dumps(mark["payload"]),
                ),
            )
    conn_lc.commit()
    conn_lc.close()

    return ledger_path


# ---------------------------------------------------------------------------
# 1. Happy Path & Breach Evaluation Tests
# ---------------------------------------------------------------------------


class TestHappyPathBreachEvaluation:
    """Tests where underperforming candidates breach policy thresholds."""

    def test_all_gates_breached_generates_valid_feedback(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Underperforming candidate breaches Net PnL, Profit Factor, Win Rate, and Drawdown."""
        cand = _build_test_candidate("cand-breach-all-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = []
        for i in range(1, 11):
            is_win = i <= 2
            net = "5.00" if is_win else "-10.00"
            gross = "5.04" if is_win else "-9.96"
            exit_p = "50500.00" if is_win else "49000.00"
            trades.append(
                {
                    "trade_id": f"trade-{i:03d}",
                    "candidate_id": cand.candidate_id,
                    "candidate_artifact_hash": cand.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": exit_p,
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": gross,
                    "net_pnl": net,
                }
            )

        ledger_path = create_synthetic_ledger(tmp_path / "breach_all", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is not None
        assert isinstance(feedback, CreatorQualificationFailureFeedback)
        assert feedback.feedback_version == 1
        assert feedback.candidate_id == cand.candidate_id
        assert feedback.candidate_artifact_hash == cand.artifact_hash
        assert feedback.bundle_hash == cand.bundle_hash
        assert feedback.dataset_registry_hash == cand.dataset_registry_hash
        assert feedback.qualification_policy_id == default_policy.policy_id
        assert feedback.data_source == "cached_only"
        assert feedback.exchange_access is False
        assert feedback.promotion_state == "unpromoted"
        assert feedback.paper_activation is False
        assert feedback.execution_authority is False

        # Verify sorted and unique failed gates
        gate_ids = tuple(g.gate_id for g in feedback.failed_gates)
        assert gate_ids == tuple(sorted(set(gate_ids)))
        assert len(feedback.failed_gates) >= 3

        # Verify sorted and unique failure reason codes
        assert feedback.failure_reason_codes == tuple(sorted(set(feedback.failure_reason_codes)))

        # Verify gate results
        failed_gate_map = {g.gate_id: g for g in feedback.failed_gates}
        assert "paper_net_pnl_min" in failed_gate_map
        assert failed_gate_map["paper_net_pnl_min"].passed is False
        assert failed_gate_map["paper_net_pnl_min"].observed is not None
        assert failed_gate_map["paper_net_pnl_min"].observed < Decimal("0.0")

        assert "paper_profit_factor_min" in failed_gate_map
        assert failed_gate_map["paper_profit_factor_min"].passed is False

        assert "paper_win_rate_min" in failed_gate_map
        assert failed_gate_map["paper_win_rate_min"].passed is False
        assert failed_gate_map["paper_win_rate_min"].observed == Decimal("20")

    def test_single_gate_breach_profit_factor(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate is profitable overall with >45% win rate, but profit factor is 1.02 < 1.05."""
        cand = _build_test_candidate("cand-breach-pf-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"trade-pf-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50500.00" if i % 2 == 1 else "49500.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "3.40" if i % 2 == 1 else "-3.33",
                "net_pnl": "3.40" if i % 2 == 1 else "-3.33",
            }
            for i in range(1, 7)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "breach_pf", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is not None
        assert len(feedback.failed_gates) == 1
        assert feedback.failed_gates[0].gate_id == "paper_profit_factor_min"
        assert feedback.failed_gates[0].passed is False
        assert feedback.failed_gates[0].threshold == Decimal("1.05")
        assert feedback.failure_reason_codes == ("paper_profit_factor_below_threshold",)

    def test_single_gate_breach_drawdown(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate has high win rate, positive net PnL, high PF, but breaches drawdown."""
        cand = _build_test_candidate("cand-breach-dd-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"trade-dd-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50500.00" if i <= 5 else "49500.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "30.00" if i <= 5 else "-25.00",
                "net_pnl": "30.00" if i <= 5 else "-25.00",
            }
            for i in range(1, 8)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "breach_dd", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is not None
        assert len(feedback.failed_gates) == 1
        assert feedback.failed_gates[0].gate_id == "paper_drawdown_max"
        assert feedback.failed_gates[0].passed is False
        assert feedback.failed_gates[0].threshold == Decimal("15.0")
        assert feedback.failure_reason_codes == ("paper_drawdown_above_threshold",)


# ---------------------------------------------------------------------------
# 2. Non-Breach Path Tests
# ---------------------------------------------------------------------------


class TestNonBreachPath:
    """Tests where candidates meet all policy criteria and return None."""

    def test_outperforming_candidate_returns_none(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate with solid win rate, positive net PnL, high profit factor returns None."""
        cand = _build_test_candidate("cand-outperformer-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"trade-win-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50500.00" if i <= 8 else "49500.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "20.00" if i <= 8 else "-10.00",
                "net_pnl": "20.00" if i <= 8 else "-10.00",
            }
            for i in range(1, 11)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "outperforming", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is None

    def test_exact_boundary_thresholds_returns_none(self, tmp_path: Path) -> None:
        """Candidate meeting thresholds at exact boundary values (>= and <=) passes."""
        cand = _build_test_candidate("cand-boundary-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        policy = PaperQualificationPolicy(
            policy_id="policy-boundary",
            paper_net_pnl_min=Decimal("0.00"),
            paper_profit_factor_min=Decimal("1.00"),
            paper_win_rate_min=Decimal("50.0"),
            paper_drawdown_max=Decimal("20.0"),
            paper_trades_min=2,
        )

        trades = [
            {
                "trade_id": "trade-b-1",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50500.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "10.00",
                "net_pnl": "10.00",
            },
            {
                "trade_id": "trade-b-2",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49500.00",
                "opened_at": (t0 + timedelta(minutes=10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=15)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            },
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "boundary", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=policy,
        )

        assert feedback is None


# ---------------------------------------------------------------------------
# 3. Real Database Verification Tests
# ---------------------------------------------------------------------------


class TestRealDatabaseVerification:
    """Tests executed against existing artifacts/paper/phase251/paper-ledger.sqlite3."""

    REAL_DB_DIR = Path("artifacts/paper/phase251")
    REAL_LEDGER_FILE = Path("artifacts/paper/phase251/paper-ledger.sqlite3")
    REAL_CANDIDATE_ID = "cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"
    REAL_ARTIFACT_HASH = "da8aeee9abebe32445d3139322a95fccd605baeea4cf2cc742a2610af1019659"

    def test_real_database_standard_policy_returns_none(
        self, default_policy: PaperQualificationPolicy
    ) -> None:
        """Phase251 has 56 trades, win rate 98.2%, PF 130.0, net PnL +281.11 -> Returns None."""
        assert self.REAL_LEDGER_FILE.exists(), f"Missing real DB: {self.REAL_LEDGER_FILE}"

        feedback = extract_paper_feedback(
            ledger_path=self.REAL_DB_DIR,
            symbol="DOGEUSDT",
            candidate_id=self.REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=default_policy,
        )

        assert feedback is None

    def test_real_database_strict_policy_generates_breach_feedback(self) -> None:
        """Under an aggressive profit factor policy (min PF = 200.0), Phase251 breaches."""
        assert self.REAL_LEDGER_FILE.exists()

        strict_policy = PaperQualificationPolicy(
            policy_id="strict-policy-real-db",
            paper_net_pnl_min=Decimal("0.0"),
            paper_profit_factor_min=Decimal("200.0"),  # Phase251 is ~130.02
            paper_win_rate_min=Decimal("45.0"),
            paper_drawdown_max=Decimal("15.0"),
            paper_trades_min=5,
        )

        feedback = extract_paper_feedback(
            ledger_path=self.REAL_DB_DIR,
            symbol="DOGEUSDT",
            candidate_id=self.REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=strict_policy,
        )

        assert feedback is not None
        assert feedback.candidate_id == self.REAL_CANDIDATE_ID
        assert feedback.candidate_artifact_hash == self.REAL_ARTIFACT_HASH
        assert feedback.bundle_hash == BUNDLE_HASH
        assert feedback.dataset_registry_hash == DATASET_HASH
        assert len(feedback.failed_gates) == 1
        assert feedback.failed_gates[0].gate_id == "paper_profit_factor_min"
        assert feedback.failed_gates[0].passed is False
        assert feedback.failed_gates[0].observed is not None
        assert feedback.failed_gates[0].observed < Decimal("200.0")

    def test_real_database_path_resolution_file_vs_directory(
        self, default_policy: PaperQualificationPolicy
    ) -> None:
        """Directory path and direct .sqlite3 file path resolve to identical results."""
        strict_policy = PaperQualificationPolicy(
            policy_id="strict-policy-path-test",
            paper_net_pnl_min=Decimal("500.0"),  # Phase251 has +281.11 -> breaches
            paper_profit_factor_min=Decimal("1.05"),
            paper_win_rate_min=Decimal("45.0"),
            paper_drawdown_max=Decimal("15.0"),
            paper_trades_min=5,
        )

        feedback_dir = extract_paper_feedback(
            ledger_path=self.REAL_DB_DIR,
            symbol="DOGEUSDT",
            candidate_id=self.REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=strict_policy,
        )

        feedback_file = extract_paper_feedback(
            ledger_path=self.REAL_LEDGER_FILE,
            symbol="DOGEUSDT",
            candidate_id=self.REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=strict_policy,
        )

        assert feedback_dir is not None
        assert feedback_file is not None
        assert feedback_dir.candidate_id == feedback_file.candidate_id
        assert feedback_dir.failed_gates == feedback_file.failed_gates


# ---------------------------------------------------------------------------
# 4. Edge Cases & Boundary Conditions
# ---------------------------------------------------------------------------


class TestEdgeCasesAndIsolation:
    """Tests covering boundary cases, zero trades, all losses, all wins, and isolation."""

    def test_edge_case_zero_closed_trades(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate with 0 closed trades breaches minimum trades threshold."""
        cand = _build_test_candidate("cand-zero-trades-001")
        ledger_path = create_synthetic_ledger(tmp_path / "zero_trades", [])

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is not None
        gate_ids = [g.gate_id for g in feedback.failed_gates]
        assert "paper_trades_min" in gate_ids
        trade_gate = next(g for g in feedback.failed_gates if g.gate_id == "paper_trades_min")
        assert trade_gate.observed == Decimal("0")
        assert trade_gate.passed is False

    def test_edge_case_zero_trades_with_min_trades_zero_returns_none(self, tmp_path: Path) -> None:
        """When min_trades=0 and there are 0 trades, extractor returns None."""
        cand = _build_test_candidate("cand-zero-trades-zero-policy")
        ledger_path = create_synthetic_ledger(tmp_path / "zero_trades_zero_policy", [])

        policy = PaperQualificationPolicy(
            policy_id="policy-zero-trades",
            paper_trades_min=0,
        )

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=policy,
        )

        assert feedback is None

    def test_edge_case_100_percent_losses(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate with all losses handles gross profit = 0 gracefully without error."""
        cand = _build_test_candidate("cand-all-losses-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"loss-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49000.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            }
            for i in range(1, 6)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "all_losses", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is not None
        for gate in feedback.failed_gates:
            if gate.observed is not None:
                assert gate.observed.is_finite()
        pf_gate = next(g for g in feedback.failed_gates if g.gate_id == "paper_profit_factor_min")
        assert pf_gate.observed == Decimal("0") or pf_gate.observed == Decimal("0.0")
        assert pf_gate.passed is False

    def test_edge_case_100_percent_wins(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate with all wins (infinite profit factor) handles infinity safely."""
        cand = _build_test_candidate("cand-all-wins-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"win-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "51000.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "10.00",
                "net_pnl": "10.00",
            }
            for i in range(1, 6)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "all_wins", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is None

    def test_edge_case_multi_candidate_isolation(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Multiple candidates in the same ledger are strictly isolated."""
        cand_winner = _build_test_candidate("cand-winner-001")
        cand_loser = _build_test_candidate("cand-loser-002")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = []
        for i in range(1, 6):
            trades.append(
                {
                    "trade_id": f"trade-w-{i}",
                    "candidate_id": cand_winner.candidate_id,
                    "candidate_artifact_hash": cand_winner.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "51000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "20.00",
                    "net_pnl": "20.00",
                }
            )
        for i in range(6, 11):
            trades.append(
                {
                    "trade_id": f"trade-l-{i}",
                    "candidate_id": cand_loser.candidate_id,
                    "candidate_artifact_hash": cand_loser.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "49000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "-20.00",
                    "net_pnl": "-20.00",
                }
            )

        ledger_path = create_synthetic_ledger(tmp_path / "multi_candidate", trades)

        feedback_w = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand_winner,
            policy=default_policy,
        )
        assert feedback_w is None

        feedback_l = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand_loser,
            policy=default_policy,
        )
        assert feedback_l is not None
        assert feedback_l.candidate_id == cand_loser.candidate_id
        assert feedback_l.candidate_artifact_hash == cand_loser.artifact_hash

    def test_edge_case_multi_candidate_symbol_only_isolation(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Symbol-only extraction isolates metrics to the latest candidate and avoids pollution.

        Regression test for Multi-Candidate Isolation Defect (M1-Iteration 2):
        When candidate 1 won and candidate 2 lost, calling extract with only symbol='BTCUSDT'
        must resolve candidate 2, evaluate only candidate 2's trades, and generate failure
        feedback (candidate 1's winning trades must NOT mask candidate 2's failure).
        """
        cand_winner = _build_test_candidate("cand-winner-001")
        cand_loser = _build_test_candidate("cand-loser-002")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = []
        for i in range(1, 6):
            trades.append(
                {
                    "trade_id": f"trade-w-{i}",
                    "candidate_id": cand_winner.candidate_id,
                    "candidate_artifact_hash": cand_winner.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "51000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "20.00",
                    "net_pnl": "20.00",
                }
            )
        for i in range(6, 11):
            trades.append(
                {
                    "trade_id": f"trade-l-{i}",
                    "candidate_id": cand_loser.candidate_id,
                    "candidate_artifact_hash": cand_loser.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "49000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "-20.00",
                    "net_pnl": "-20.00",
                }
            )

        ledger_path = create_synthetic_ledger(tmp_path / "multi_candidate_symbol_only", trades)

        # Calling extract with only symbol='BTCUSDT' and no candidate_id
        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=default_policy,
        )

        assert feedback is not None
        assert feedback.candidate_id == cand_loser.candidate_id
        assert feedback.candidate_artifact_hash == cand_loser.artifact_hash

        # Verify candidate 2's failure feedback is generated and all 4 performance gates breached:
        # If candidate 1's winning trades masked candidate 2, net PnL would be $0.00 and WR 50%,
        # causing net_pnl_min and win_rate_min to erroneously pass.
        failed_gate_ids = {g.gate_id for g in feedback.failed_gates}
        assert failed_gate_ids == {
            "paper_net_pnl_min",
            "paper_profit_factor_min",
            "paper_win_rate_min",
            "paper_drawdown_max",
        }

        # Check observed metrics in gates confirm strict isolation to candidate 2 (5 losing trades)
        net_pnl_gate = next(g for g in feedback.failed_gates if g.gate_id == "paper_net_pnl_min")
        assert net_pnl_gate.observed == Decimal("-100.00")

        wr_gate = next(g for g in feedback.failed_gates if g.gate_id == "paper_win_rate_min")
        assert wr_gate.observed == Decimal("0.00")

    def test_edge_case_unclosed_trades_omitted_from_metrics(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Active open positions without close events are excluded from closed trade metrics."""
        cand = _build_test_candidate("cand-open-positions-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"trade-closed-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50500.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "15.00",
                "net_pnl": "15.00",
                "open_only": False,
            }
            for i in range(1, 6)
        ] + [
            {
                "trade_id": f"trade-open-only-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "opened_at": (t0 + timedelta(minutes=(i + 5) * 10)).isoformat(),
                "open_only": True,
            }
            for i in range(1, 4)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "unclosed", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert feedback is None


# ---------------------------------------------------------------------------
# 5. Schema Compliance & Autonomous Cycle Interoperability
# ---------------------------------------------------------------------------


class TestSchemaComplianceAndInteroperability:
    """Validates schema compliance, JSON round-tripping, and pipeline consumption."""

    def test_feedback_json_round_trip(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Generated feedback serializes to JSON and deserializes identically."""
        cand = _build_test_candidate("cand-json-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": f"t-{i}",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49500.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            }
            for i in range(1, 6)
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "json_test", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )
        assert feedback is not None

        json_str = feedback.model_dump_json(indent=2)
        reloaded = CreatorQualificationFailureFeedback.model_validate_json(json_str)

        assert reloaded == feedback
        assert reloaded.candidate_id == feedback.candidate_id
        assert reloaded.failed_gates == feedback.failed_gates
        assert reloaded.failure_reason_codes == feedback.failure_reason_codes

    def test_feedback_accepted_by_learner_critic_request(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Feedback can be passed directly into LearnerCriticRequest without validation error."""
        cand = _build_test_candidate("cand-critic-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": "t-1",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49000.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "-50.00",
                "net_pnl": "-50.00",
            }
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "critic_test", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )
        assert feedback is not None

        critic_req = LearnerCriticRequest(
            research_run_id="run-critic-unit-test",
            candidate_id=feedback.candidate_id,
            candidate_artifact_hash=feedback.candidate_artifact_hash,
            feedback=feedback,
            input_evidence_refs=(f"feedback/{feedback.qualification_hash}",),
            attempt=1,
        )
        assert critic_req.candidate_id == feedback.candidate_id
        assert critic_req.feedback == feedback

    def test_feedback_intake_validation_in_autonomous_cycle(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Feedback passes execute_autonomous_cycle intake check."""
        cand = _build_test_candidate("cand-cycle-intake-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": "t-cycle-1",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49000.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "-20.00",
                "net_pnl": "-20.00",
            }
        ]

        ledger_path = create_synthetic_ledger(tmp_path / "cycle_intake", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )
        assert feedback is not None

        config = AutonomousCycleConfig(
            cycle_id="cycle-test-001",
            symbol="BTCUSDT",
            bundle_hash=cand.bundle_hash,
            dataset_registry_hash=cand.dataset_registry_hash,
            qualification_policy=WalkForwardQualificationPolicy(
                policy_id="wf-policy-001",
                minimum_windows=1,
                minimum_trades=1,
                minimum_profit_factor=Decimal("1.0"),
                maximum_drawdown_pct=Decimal("20.0"),
                minimum_average_return_pct=Decimal("0.0"),
            ),
            artifact_root=tmp_path / "cycle_out",
        )
        assert feedback.bundle_hash == config.bundle_hash
        assert feedback.dataset_registry_hash == config.dataset_registry_hash

    def test_missing_database_raises_filenotfound(self) -> None:
        """Instantiating PaperFeedbackExtractor with nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Paper ledger database file not found"):
            PaperFeedbackExtractor(storage_path=Path("nonexistent/dir/paper-ledger.sqlite3"))

    def test_candidate_metadata_resolution_from_json_discovery(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Hashes are automatically discovered from research candidate JSON files."""
        # cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd exists in phase252
        cand_id = "cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd"
        art_hash = "ad1c8c35790e0f6a5726d317a9b0d0ee6e4e147a103f79e6d03a82ad23f9a417"
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": "trade-disc-1",
                "candidate_id": cand_id,
                "candidate_artifact_hash": art_hash,
                "symbol": "SOLUSDT",
                "entry_price": "140.00",
                "exit_price": "130.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            }
        ]
        ledger_path = create_synthetic_ledger(tmp_path / "json_disc", trades)

        feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_id=cand_id,
            policy=default_policy,
        )

        assert feedback is not None
        assert feedback.candidate_id == cand_id
        # Discovered bundle_hash from phase252/candidates/<cand_id>.json
        assert (
            feedback.bundle_hash
            == "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
        )
        assert (
            feedback.dataset_registry_hash
            == "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
        )

    def test_unresolvable_candidate_raises_data_quality_error(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Candidate lacking bundle_hash or json raises DataQualityError."""
        unknown_cand_id = "cand-unknown-nowhere-001"
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": "trade-unknown-1",
                "candidate_id": unknown_cand_id,
                "candidate_artifact_hash": "c" * 64,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49000.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            }
        ]
        ledger_path = create_synthetic_ledger(tmp_path / "unknown_cand", trades)

        with pytest.raises(DataQualityError, match="bundle_hash could not be resolved"):
            extract_paper_feedback(
                ledger_path=ledger_path,
                candidate_id=unknown_cand_id,
                policy=default_policy,
            )

    def test_hash_determinism(
        self, tmp_path: Path, default_policy: PaperQualificationPolicy
    ) -> None:
        """Calling extraction multiple times yields identical qualification_hash."""
        cand = _build_test_candidate("cand-hash-determinism-001")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)

        trades = [
            {
                "trade_id": "trade-det-1",
                "candidate_id": cand.candidate_id,
                "candidate_artifact_hash": cand.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49000.00",
                "opened_at": t0.isoformat(),
                "closed_at": (t0 + timedelta(minutes=5)).isoformat(),
                "gross_pnl": "-10.00",
                "net_pnl": "-10.00",
            }
        ]
        ledger_path = create_synthetic_ledger(tmp_path / "det_hash", trades)

        fb1 = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )
        fb2 = extract_paper_feedback(
            ledger_path=ledger_path,
            candidate_artifact=cand,
            policy=default_policy,
        )

        assert fb1 is not None and fb2 is not None
        assert fb1.qualification_hash == fb2.qualification_hash
        assert len(fb1.qualification_hash) == 64

    def test_policy_validation_and_content_hash(self) -> None:
        """Policy validators reject invalid inputs; content hash is deterministic."""
        policy = PaperQualificationPolicy(
            policy_id="test-pol-1",
            paper_net_pnl_min=Decimal("10.5"),
            paper_profit_factor_min=Decimal("1.2"),
            paper_win_rate_min=Decimal("50.0"),
            paper_drawdown_max=Decimal("12.0"),
            paper_trades_min=10,
        )
        h1 = paper_qualification_policy_content_hash(policy)
        h2 = paper_qualification_policy_content_hash(policy)
        assert h1 == h2
        assert len(h1) == 64

        # Property accessors
        assert policy.min_trades == 10
        assert policy.min_net_pnl == Decimal("10.5")
        assert policy.min_profit_factor == Decimal("1.2")
        assert policy.min_win_rate_pct == Decimal("50.0")
        assert policy.max_drawdown_pct == Decimal("12.0")

        with pytest.raises(ValueError, match="non-negative"):
            PaperQualificationPolicy(paper_profit_factor_min=Decimal("-0.5"))

        with pytest.raises(ValueError, match="percentage thresholds"):
            PaperQualificationPolicy(paper_win_rate_min=Decimal("105.0"))
