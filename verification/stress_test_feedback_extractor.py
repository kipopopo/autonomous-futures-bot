"""Empirical stress test suite for PaperFeedbackExtractor.

Executes adversarial edge cases across:
1. Zero closed trades with various paper_trades_min policies.
2. 100% winning trades (infinite profit factor).
3. 100% losing trades (zero profit factor).
4. Breakeven trades (gross profit = 0, gross loss = 0).
5. Exact boundary thresholds (observed == threshold and epsilon shifts).
6. Multiple candidate IDs coexisting in the same SQLite ledger.
7. Non-existent candidate IDs or symbols.
8. Missing or empty lifecycle database (0-byte, empty tables, corrupted payloads).
9. Hash determinism and consumer schema compatibility.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.analytics.metrics import calculate_performance_metrics
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
    compute_feedback_qualification_hash,
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
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)

BUNDLE_HASH = "a" * 64
DATASET_HASH = "b" * 64
NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


def build_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    bundle_hash: str = BUNDLE_HASH,
    dataset_hash: str = DATASET_HASH,
) -> CreatorCandidateArtifact:
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
        creator_run_id="run-stress-001",
        research_seed=42,
        created_at=NOW,
    )


def create_synthetic_db(
    storage_dir: Path,
    trades: Sequence[dict[str, Any]],
    lifecycle_marks: Sequence[dict[str, Any]] | None = None,
    create_lifecycle: bool = True,
    corrupt_lifecycle: bool = False,
    empty_lifecycle: bool = False,
) -> Path:
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
    if corrupt_lifecycle:
        # Write 0 bytes or random unparseable bytes
        lifecycle_path.write_bytes(b"NOT_A_VALID_SQLITE_DATABASE_CORRUPTED_BYTES")
    elif empty_lifecycle:
        # 0 bytes file
        lifecycle_path.write_bytes(b"")
    elif create_lifecycle:
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
                raw_payload = (
                    mark["payload"]
                    if isinstance(mark["payload"], str)
                    else json.dumps(mark["payload"])
                )
                conn_lc.execute(
                    "INSERT INTO paper_lifecycle_marks VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        i,
                        mark["candidate_id"],
                        mark["candidate_artifact_hash"],
                        mark["trade_id"],
                        mark["marked_at"],
                        raw_payload,
                    ),
                )
        conn_lc.commit()
        conn_lc.close()

    return ledger_path


def run_all_stress_tests() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def record(name: str, passed: bool, details: str) -> None:
        results.append({"test": name, "passed": passed, "details": details})
        status_str = "PASS" if passed else "FAIL"
        print(f"[{status_str}] {name}: {details}")

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_base = Path(tmp_dir_str)

        # -------------------------------------------------------------------
        # Suite 1: Zero closed trades with various paper_trades_min policies
        # -------------------------------------------------------------------
        cand1 = build_candidate("cand-stress-zero-001")
        db_zero = create_synthetic_db(tmp_base / "suite1_zero", [])

        # 1.1: paper_trades_min == 0 -> returns None
        p0 = PaperQualificationPolicy(policy_id="p-zero", paper_trades_min=0)
        fb_p0 = extract_paper_feedback(ledger_path=db_zero, candidate_artifact=cand1, policy=p0)
        record(
            "1.1_zero_trades_min_0_returns_none",
            fb_p0 is None,
            f"Expected None, got: {fb_p0}",
        )

        # 1.2: paper_trades_min == 1 -> single failed gate
        p1 = PaperQualificationPolicy(policy_id="p-one", paper_trades_min=1)
        fb_p1 = extract_paper_feedback(ledger_path=db_zero, candidate_artifact=cand1, policy=p1)
        passed_1_2 = (
            fb_p1 is not None
            and len(fb_p1.failed_gates) == 1
            and fb_p1.failed_gates[0].gate_id == "paper_trades_min"
            and fb_p1.failed_gates[0].observed == Decimal("0")
            and fb_p1.failed_gates[0].passed is False
        )
        record(
            "1.2_zero_trades_min_1_single_breach",
            passed_1_2,
            f"Failed gates: {[g.gate_id for g in fb_p1.failed_gates] if fb_p1 else None}",
        )

        # 1.3: paper_trades_min == 100 -> single failed gate with threshold 100
        p100 = PaperQualificationPolicy(policy_id="p-hundred", paper_trades_min=100)
        fb_p100 = extract_paper_feedback(
            ledger_path=db_zero, candidate_artifact=cand1, policy=p100
        )
        passed_1_3 = (
            fb_p100 is not None
            and len(fb_p100.failed_gates) == 1
            and fb_p100.failed_gates[0].threshold == Decimal("100")
        )
        record(
            "1.3_zero_trades_min_100_threshold_check",
            passed_1_3,
            f"Threshold observed: {fb_p100.failed_gates[0].threshold if fb_p100 else None}",
        )

        # -------------------------------------------------------------------
        # Suite 2: 100% winning trades (infinite profit factor)
        # -------------------------------------------------------------------
        cand2 = build_candidate("cand-stress-wins-002")
        t0 = datetime(2026, 9, 8, 1, 0, 0, tzinfo=UTC)
        trades_wins = [
            {
                "trade_id": f"win-{i}",
                "candidate_id": cand2.candidate_id,
                "candidate_artifact_hash": cand2.artifact_hash,
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
        db_wins = create_synthetic_db(tmp_base / "suite2_wins", trades_wins)

        # 2.1: 5 wins under default policy -> returns None (all gates pass, pf is None/infinite)
        p_def = PaperQualificationPolicy()
        fb_w1 = extract_paper_feedback(
            ledger_path=db_wins, candidate_artifact=cand2, policy=p_def
        )
        record(
            "2.1_100pct_wins_default_policy_returns_none",
            fb_w1 is None,
            f"Expected None, got: {fb_w1}",
        )

        # 2.2: 5 wins with strict net PnL policy (net_pnl_min = 1000.00 while actual is 50.00)
        p_strict_pnl = PaperQualificationPolicy(paper_net_pnl_min=Decimal("1000.00"))
        fb_w2 = extract_paper_feedback(
            ledger_path=db_wins, candidate_artifact=cand2, policy=p_strict_pnl
        )
        passed_2_2 = (
            fb_w2 is not None
            and len(fb_w2.failed_gates) == 1
            and fb_w2.failed_gates[0].gate_id == "paper_net_pnl_min"
        )
        record(
            "2.2_100pct_wins_strict_pnl_infinite_pf_preserved",
            passed_2_2,
            f"Failed gates: {[g.gate_id for g in fb_w2.failed_gates] if fb_w2 else None}",
        )

        # 2.3: Microscopic wins (100 trades, 0.0001 net PnL each)
        cand2_micro = build_candidate("cand-stress-micro-003")
        trades_micro = [
            {
                "trade_id": f"micro-{i}",
                "candidate_id": cand2_micro.candidate_id,
                "candidate_artifact_hash": cand2_micro.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50000.01",
                "opened_at": (t0 + timedelta(minutes=i * 2)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 2 + 1)).isoformat(),
                "gross_pnl": "0.0001",
                "net_pnl": "0.0001",
            }
            for i in range(1, 101)
        ]
        db_micro = create_synthetic_db(tmp_base / "suite2_micro", trades_micro)
        fb_micro = extract_paper_feedback(
            ledger_path=db_micro,
            candidate_artifact=cand2_micro,
            policy=PaperQualificationPolicy(paper_trades_min=50, paper_net_pnl_min=Decimal("0.00")),
        )
        record(
            "2.3_100_microscopic_wins_precision_handling",
            fb_micro is None,
            f"Expected None (all gates pass), got: {fb_micro}",
        )

        # -------------------------------------------------------------------
        # Suite 3: 100% losing trades (zero profit factor)
        # -------------------------------------------------------------------
        cand3 = build_candidate("cand-stress-losses-003")
        trades_losses = [
            {
                "trade_id": f"loss-{i}",
                "candidate_id": cand3.candidate_id,
                "candidate_artifact_hash": cand3.artifact_hash,
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
        db_losses = create_synthetic_db(tmp_base / "suite3_losses", trades_losses)

        # 3.1: 5 losses under default policy -> 4 performance gates fail, trades_min passes
        fb_l1 = extract_paper_feedback(
            ledger_path=db_losses, candidate_artifact=cand3, policy=p_def
        )
        passed_3_1 = (
            fb_l1 is not None
            and len(fb_l1.failed_gates) == 4
            and {g.gate_id for g in fb_l1.failed_gates}
            == {
                "paper_net_pnl_min",
                "paper_profit_factor_min",
                "paper_win_rate_min",
                "paper_drawdown_max",
            }
        )
        record(
            "3.1_100pct_losses_4_failed_gates",
            passed_3_1,
            f"Failed gates: {[g.gate_id for g in fb_l1.failed_gates] if fb_l1 else None}",
        )

        # 3.2: 100% losses with profit factor threshold = 0.0 -> PF passes!
        p_zero_pf = PaperQualificationPolicy(paper_profit_factor_min=Decimal("0.00"))
        fb_l2 = extract_paper_feedback(
            ledger_path=db_losses, candidate_artifact=cand3, policy=p_zero_pf
        )
        passed_3_2 = (
            fb_l2 is not None
            and "paper_profit_factor_min" not in {g.gate_id for g in fb_l2.failed_gates}
            and len(fb_l2.failed_gates) == 3
        )
        record(
            "3.2_100pct_losses_pf_threshold_zero_passes",
            passed_3_2,
            f"Failed gates: {[g.gate_id for g in fb_l2.failed_gates] if fb_l2 else None}",
        )

        # 3.3: Extreme loss exceeding capital (e.g. net_pnl = -500 on 100 cap -> DD = 500%)
        cand3_extreme = build_candidate("cand-stress-ext-loss-004")
        trades_extreme = [
            {
                "trade_id": f"ext-loss-{i}",
                "candidate_id": cand3_extreme.candidate_id,
                "candidate_artifact_hash": cand3_extreme.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "40000.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "-100.00",
                "net_pnl": "-100.00",
            }
            for i in range(1, 6)
        ]
        db_ext_loss = create_synthetic_db(tmp_base / "suite3_ext_loss", trades_extreme)
        fb_ext = extract_paper_feedback(
            ledger_path=db_ext_loss, candidate_artifact=cand3_extreme, policy=p_def
        )
        dd_gate = next(
            (g for g in fb_ext.failed_gates if g.gate_id == "paper_drawdown_max"), None
        ) if fb_ext else None
        passed_3_3 = (
            fb_ext is not None
            and dd_gate is not None
            and dd_gate.observed is not None
            and dd_gate.observed > Decimal("100.0")
            and dd_gate.observed.is_finite()
        )
        record(
            "3.3_drawdown_exceeding_100pct_finite_validation",
            passed_3_3,
            f"Drawdown observed: {dd_gate.observed if dd_gate else None}",
        )

        # -------------------------------------------------------------------
        # Suite 4: Breakeven trades (gross profit = 0, gross loss = 0)
        # -------------------------------------------------------------------
        cand_be = build_candidate("cand-stress-breakeven-005")
        trades_be = [
            {
                "trade_id": f"be-{i}",
                "candidate_id": cand_be.candidate_id,
                "candidate_artifact_hash": cand_be.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "50000.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "0.00",
                "net_pnl": "0.00",
            }
            for i in range(1, 6)
        ]
        db_be = create_synthetic_db(tmp_base / "suite4_be", trades_be)
        fb_be = extract_paper_feedback(
            ledger_path=db_be, candidate_artifact=cand_be, policy=p_def
        )
        pf_gate_be = next(
            (g for g in fb_be.failed_gates if g.gate_id == "paper_profit_factor_min"), None
        ) if fb_be else None
        passed_4 = (
            fb_be is not None
            and pf_gate_be is not None
            and pf_gate_be.observed == Decimal("0.00")
            and pf_gate_be.reason_code == "paper_profit_factor_missing"
        )
        record(
            "4.1_breakeven_trades_reason_code_and_observed",
            passed_4,
            f"PF reason: {pf_gate_be.reason_code if pf_gate_be else None}, observed: {pf_gate_be.observed if pf_gate_be else None}",
        )

        # -------------------------------------------------------------------
        # Suite 5: Exact boundary thresholds (observed == threshold)
        # -------------------------------------------------------------------
        cand5 = build_candidate("cand-stress-boundary-006")
        # Construct trades with:
        # total_trades = 5
        # 3 wins of +$10, 2 losses of -$5
        # net_pnl = 3*10 - 2*5 = 30 - 10 = +20.00
        # win_rate = 3/5 = 60.0%
        # profit_factor = 30.0 / 10.0 = 3.0
        # drawdown: high water mark = 100 + 30 = 130. Then 2 losses of 5 -> equity 120. dd = 10 / 130 = 7.6923%
        trades_boundary = [
            # 3 wins
            {
                "trade_id": f"b-win-{i}",
                "candidate_id": cand5.candidate_id,
                "candidate_artifact_hash": cand5.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "51000.00",
                "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                "gross_pnl": "10.00",
                "net_pnl": "10.00",
            }
            for i in range(1, 4)
        ] + [
            # 2 losses
            {
                "trade_id": f"b-loss-{i}",
                "candidate_id": cand5.candidate_id,
                "candidate_artifact_hash": cand5.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49500.00",
                "opened_at": (t0 + timedelta(minutes=(i + 3) * 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=(i + 3) * 10 + 5)).isoformat(),
                "gross_pnl": "-5.00",
                "net_pnl": "-5.00",
            }
            for i in range(1, 3)
        ]
        db_boundary = create_synthetic_db(tmp_base / "suite5_boundary", trades_boundary)

        # 5.1: Exact threshold match policy
        # Observed: trades=5, net_pnl=20.00, pf=3.0, wr=60.0, dd=7.6923
        p_exact = PaperQualificationPolicy(
            policy_id="p-exact",
            paper_trades_min=5,
            paper_net_pnl_min=Decimal("20.00"),
            paper_profit_factor_min=Decimal("3.00"),
            paper_win_rate_min=Decimal("60.00"),
            paper_drawdown_max=Decimal("7.6923"),
        )
        fb_exact = extract_paper_feedback(
            ledger_path=db_boundary, candidate_artifact=cand5, policy=p_exact
        )
        record(
            "5.1_all_gates_exact_threshold_match_returns_none",
            fb_exact is None,
            f"Expected None, got: {fb_exact}",
        )

        # 5.2: Epsilon shifts triggering single breaches:
        # 5.2a: trades_min = 6 -> breaches
        fb_eps_trades = extract_paper_feedback(
            ledger_path=db_boundary,
            candidate_artifact=cand5,
            policy=p_exact.model_copy(update={"paper_trades_min": 6}),
        )
        record(
            "5.2a_epsilon_trades_min_6_breaches",
            fb_eps_trades is not None
            and len(fb_eps_trades.failed_gates) == 1
            and fb_eps_trades.failed_gates[0].gate_id == "paper_trades_min",
            f"Failed gates: {[g.gate_id for g in fb_eps_trades.failed_gates] if fb_eps_trades else None}",
        )

        # 5.2b: net_pnl_min = 20.01 -> breaches
        fb_eps_pnl = extract_paper_feedback(
            ledger_path=db_boundary,
            candidate_artifact=cand5,
            policy=p_exact.model_copy(update={"paper_net_pnl_min": Decimal("20.01")}),
        )
        record(
            "5.2b_epsilon_net_pnl_20_01_breaches",
            fb_eps_pnl is not None
            and len(fb_eps_pnl.failed_gates) == 1
            and fb_eps_pnl.failed_gates[0].gate_id == "paper_net_pnl_min",
            f"Failed gates: {[g.gate_id for g in fb_eps_pnl.failed_gates] if fb_eps_pnl else None}",
        )

        # 5.2c: profit_factor_min = 3.0001 -> breaches
        fb_eps_pf = extract_paper_feedback(
            ledger_path=db_boundary,
            candidate_artifact=cand5,
            policy=p_exact.model_copy(update={"paper_profit_factor_min": Decimal("3.0001")}),
        )
        record(
            "5.2c_epsilon_profit_factor_3_0001_breaches",
            fb_eps_pf is not None
            and len(fb_eps_pf.failed_gates) == 1
            and fb_eps_pf.failed_gates[0].gate_id == "paper_profit_factor_min",
            f"Failed gates: {[g.gate_id for g in fb_eps_pf.failed_gates] if fb_eps_pf else None}",
        )

        # 5.2d: win_rate_min = 60.01 -> breaches
        fb_eps_wr = extract_paper_feedback(
            ledger_path=db_boundary,
            candidate_artifact=cand5,
            policy=p_exact.model_copy(update={"paper_win_rate_min": Decimal("60.01")}),
        )
        record(
            "5.2d_epsilon_win_rate_60_01_breaches",
            fb_eps_wr is not None
            and len(fb_eps_wr.failed_gates) == 1
            and fb_eps_wr.failed_gates[0].gate_id == "paper_win_rate_min",
            f"Failed gates: {[g.gate_id for g in fb_eps_wr.failed_gates] if fb_eps_wr else None}",
        )

        # 5.2e: drawdown_max = 7.6922 (observed is 7.6923) -> breaches
        fb_eps_dd = extract_paper_feedback(
            ledger_path=db_boundary,
            candidate_artifact=cand5,
            policy=p_exact.model_copy(update={"paper_drawdown_max": Decimal("7.6922")}),
        )
        record(
            "5.2e_epsilon_drawdown_7_6922_breaches",
            fb_eps_dd is not None
            and len(fb_eps_dd.failed_gates) == 1
            and fb_eps_dd.failed_gates[0].gate_id == "paper_drawdown_max",
            f"Failed gates: {[g.gate_id for g in fb_eps_dd.failed_gates] if fb_eps_dd else None}",
        )

        # -------------------------------------------------------------------
        # Suite 6: Multiple candidate IDs coexisting in same SQLite ledger
        # -------------------------------------------------------------------
        cand_winner = build_candidate("cand-multi-winner-001")
        cand_loser = build_candidate("cand-multi-loser-002")
        cand_idle = build_candidate("cand-multi-idle-003")

        multi_trades = []
        for i in range(1, 6):
            multi_trades.append(
                {
                    "trade_id": f"t-w-{i}",
                    "candidate_id": cand_winner.candidate_id,
                    "candidate_artifact_hash": cand_winner.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "51000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "25.00",
                    "net_pnl": "25.00",
                }
            )
        for i in range(6, 11):
            multi_trades.append(
                {
                    "trade_id": f"t-l-{i}",
                    "candidate_id": cand_loser.candidate_id,
                    "candidate_artifact_hash": cand_loser.artifact_hash,
                    "symbol": "BTCUSDT",
                    "entry_price": "50000.00",
                    "exit_price": "49000.00",
                    "opened_at": (t0 + timedelta(minutes=i * 10)).isoformat(),
                    "closed_at": (t0 + timedelta(minutes=i * 10 + 5)).isoformat(),
                    "gross_pnl": "-25.00",
                    "net_pnl": "-25.00",
                }
            )
        db_multi = create_synthetic_db(tmp_base / "suite6_multi", multi_trades)

        # 6.1: Candidate Winner -> returns None
        fb_mw = extract_paper_feedback(
            ledger_path=db_multi, candidate_artifact=cand_winner, policy=p_def
        )
        record(
            "6.1_multi_candidate_winner_isolated_returns_none",
            fb_mw is None,
            f"Expected None, got: {fb_mw}",
        )

        # 6.2: Candidate Loser -> returns breach feedback
        fb_ml = extract_paper_feedback(
            ledger_path=db_multi, candidate_artifact=cand_loser, policy=p_def
        )
        passed_6_2 = (
            fb_ml is not None
            and fb_ml.candidate_id == cand_loser.candidate_id
            and fb_ml.candidate_artifact_hash == cand_loser.artifact_hash
            and len(fb_ml.failed_gates) == 4
        )
        record(
            "6.2_multi_candidate_loser_isolated_breaches",
            passed_6_2,
            f"Candidate ID: {fb_ml.candidate_id if fb_ml else None}, failed: {len(fb_ml.failed_gates) if fb_ml else 0}",
        )

        # 6.3: Candidate Idle (0 trades in multi-candidate DB) -> breaches paper_trades_min
        fb_mi = extract_paper_feedback(
            ledger_path=db_multi, candidate_artifact=cand_idle, policy=p_def
        )
        passed_6_3 = (
            fb_mi is not None
            and fb_mi.candidate_id == cand_idle.candidate_id
            and len(fb_mi.failed_gates) == 1
            and fb_mi.failed_gates[0].gate_id == "paper_trades_min"
            and fb_mi.failed_gates[0].observed == Decimal("0")
        )
        record(
            "6.3_multi_candidate_idle_zero_trades_breaches_trades_min",
            passed_6_3,
            f"Candidate ID: {fb_mi.candidate_id if fb_mi else None}, failed: {[g.gate_id for g in fb_mi.failed_gates] if fb_mi else []}",
        )

        # 6.4: Symbol-only extraction with multiple candidates in ledger
        # In a ledger where cand_winner has 5 wins and cand_loser has 5 losses (latest trades),
        # if extract_paper_feedback is called with symbol="BTCUSDT" and no candidate_id,
        # meta.candidate_id resolves to cand_loser.
        # Check whether metrics are isolated to cand_loser (5 trades, all losses)
        # or polluted by cand_winner (10 trades total).
        fb_sym_multi = extract_paper_feedback(
            ledger_path=db_multi,
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=p_def,
        )
        # Check trades gate or failed gates count:
        # If isolated to cand_loser: 5 trades, net_pnl = -125.00, win_rate = 0%, PF = 0.0 -> 4 failed gates
        # If polluted: 10 trades, net_pnl = 0.00, win_rate = 50%, PF = 1.00 (below 1.05) -> only PF fails
        is_isolated = (
            fb_sym_multi is not None
            and fb_sym_multi.candidate_id == cand_loser.candidate_id
            and len(fb_sym_multi.failed_gates) == 4
        )
        record(
            "6.4_multi_candidate_symbol_only_isolation_check",
            is_isolated,
            f"Resolved candidate: {fb_sym_multi.candidate_id if fb_sym_multi else None}, failed gates: {[g.gate_id for g in fb_sym_multi.failed_gates] if fb_sym_multi else []} (expected 4 failed gates if isolated to cand_loser)",
        )


        # -------------------------------------------------------------------
        # Suite 7: Non-existent candidate IDs or symbols
        # -------------------------------------------------------------------
        # 7.1: Non-existent candidate ID without artifact file raises DataQualityError
        cand_nonexistent_raised = False
        try:
            extract_paper_feedback(
                ledger_path=db_multi,
                candidate_id="cand-nonexistent-999",
                symbol="BTCUSDT",
            )
        except DataQualityError as exc:
            cand_nonexistent_raised = True
            err_msg = str(exc)
        record(
            "7.1_nonexistent_candidate_id_raises_data_quality_error",
            cand_nonexistent_raised,
            f"Raised DataQualityError: {err_msg if cand_nonexistent_raised else 'None'}",
        )

        # 7.2: Non-existent symbol without candidate_id or artifact raises ValueError
        symbol_nonexistent_raised = False
        try:
            extract_paper_feedback(
                ledger_path=db_multi,
                symbol="NONEXISTENTUSDT",
            )
        except ValueError as exc:
            symbol_nonexistent_raised = True
            err_msg = str(exc)
        record(
            "7.2_nonexistent_symbol_raises_value_error",
            symbol_nonexistent_raised,
            f"Raised ValueError: {err_msg if symbol_nonexistent_raised else 'None'}",
        )

        # 7.3: Non-existent symbol with valid candidate artifact -> evaluates 0 trades, breaches trades_min
        fb_nonexistent_sym = extract_paper_feedback(
            ledger_path=db_multi,
            candidate_artifact=cand_winner,
            symbol="NONEXISTENTUSDT",
            policy=p_def,
        )
        passed_7_3 = (
            fb_nonexistent_sym is not None
            and len(fb_nonexistent_sym.failed_gates) == 1
            and fb_nonexistent_sym.failed_gates[0].gate_id == "paper_trades_min"
            and fb_nonexistent_sym.failed_gates[0].observed == Decimal("0")
        )
        record(
            "7.3_nonexistent_symbol_with_candidate_evaluates_0_trades",
            passed_7_3,
            f"Failed gates: {[g.gate_id for g in fb_nonexistent_sym.failed_gates] if fb_nonexistent_sym else None}",
        )

        # -------------------------------------------------------------------
        # Suite 8: Missing or empty lifecycle database
        # -------------------------------------------------------------------
        # 8.1: Missing lifecycle file (file does not exist)
        db_no_lc = create_synthetic_db(
            tmp_base / "suite8_no_lc", trades_losses, create_lifecycle=False
        )
        fb_no_lc = extract_paper_feedback(
            ledger_path=db_no_lc,
            candidate_artifact=cand3,
            policy=p_def,
        )
        record(
            "8.1_missing_lifecycle_db_succeeds_gracefully",
            fb_no_lc is not None and len(fb_no_lc.failed_gates) == 4,
            f"Failed gates: {len(fb_no_lc.failed_gates) if fb_no_lc else None}",
        )

        # 8.2: 0-byte empty lifecycle file
        db_empty_lc = create_synthetic_db(
            tmp_base / "suite8_empty_lc", trades_losses, empty_lifecycle=True
        )
        fb_empty_lc = extract_paper_feedback(
            ledger_path=db_empty_lc,
            candidate_artifact=cand3,
            policy=p_def,
        )
        record(
            "8.2_zero_byte_empty_lifecycle_file_succeeds_gracefully",
            fb_empty_lc is not None and len(fb_empty_lc.failed_gates) == 4,
            f"Failed gates: {len(fb_empty_lc.failed_gates) if fb_empty_lc else None}",
        )

        # 8.3: Corrupted non-SQLite bytes lifecycle file
        db_corrupt_lc = create_synthetic_db(
            tmp_base / "suite8_corrupt_lc", trades_losses, corrupt_lifecycle=True
        )
        fb_corrupt_lc = extract_paper_feedback(
            ledger_path=db_corrupt_lc,
            candidate_artifact=cand3,
            policy=p_def,
        )
        record(
            "8.3_corrupted_lifecycle_db_succeeds_gracefully",
            fb_corrupt_lc is not None and len(fb_corrupt_lc.failed_gates) == 4,
            f"Failed gates: {len(fb_corrupt_lc.failed_gates) if fb_corrupt_lc else None}",
        )

        # 8.4: Lifecycle DB with marks table containing corrupted JSON payload
        corrupt_marks = [
            {
                "candidate_id": cand3.candidate_id,
                "candidate_artifact_hash": cand3.artifact_hash,
                "trade_id": "loss-1",
                "marked_at": t0.isoformat(),
                "payload": "INVALID_JSON_CORRUPTED_PAYLOAD{{{",
            }
        ]
        db_bad_payload = create_synthetic_db(
            tmp_base / "suite8_bad_payload", trades_losses, lifecycle_marks=corrupt_marks
        )
        fb_bad_payload = extract_paper_feedback(
            ledger_path=db_bad_payload,
            candidate_artifact=cand3,
            policy=p_def,
        )
        record(
            "8.4_corrupted_json_payload_in_lifecycle_succeeds_gracefully",
            fb_bad_payload is not None and len(fb_bad_payload.failed_gates) == 4,
            f"Failed gates: {len(fb_bad_payload.failed_gates) if fb_bad_payload else None}",
        )

        # -------------------------------------------------------------------
        # Suite 9: Determinism & Schema Verification
        # -------------------------------------------------------------------
        # 9.1: Determinism across 50 iterations
        hashes = set()
        for _ in range(50):
            fb_rep = extract_paper_feedback(
                ledger_path=db_losses,
                candidate_artifact=cand3,
                policy=p_def,
            )
            assert fb_rep is not None
            hashes.add(fb_rep.qualification_hash)

        record(
            "9.1_qualification_hash_deterministic_across_50_runs",
            len(hashes) == 1,
            f"Unique hashes: {len(hashes)} (Hash: {next(iter(hashes))})",
        )

        # 9.2: Schema compliance and model_dump_json
        fb = fb_rep
        json_str = fb.model_dump_json(indent=2)
        parsed = json.loads(json_str)
        passed_9_2 = (
            parsed.get("feedback_version") == 1
            and parsed.get("candidate_id") == cand3.candidate_id
            and parsed.get("data_source") == "cached_only"
            and parsed.get("exchange_access") is False
            and parsed.get("paper_activation") is False
            and parsed.get("execution_authority") is False
            and isinstance(parsed.get("failed_gates"), list)
            and len(parsed["failed_gates"]) == 4
        )
        record(
            "9.2_model_dump_json_schema_compliance",
            passed_9_2,
            f"Version: {parsed.get('feedback_version')}, data_source: {parsed.get('data_source')}",
        )

        # 9.3: LearnerCriticRequest intake validation
        lc_req = LearnerCriticRequest(
            research_run_id="run-test-critic-001",
            candidate_id=cand3.candidate_id,
            candidate_artifact_hash=cand3.artifact_hash,
            feedback=fb,
            input_evidence_refs=("ref-1", "ref-2"),
            attempt=1,
        )
        passed_9_3 = (
            lc_req.feedback is not None
            and lc_req.feedback.candidate_id == cand3.candidate_id
            and lc_req.candidate_artifact_hash == fb.candidate_artifact_hash
        )
        record(
            "9.3_learner_critic_request_intake_validation",
            passed_9_3,
            f"Candidate: {lc_req.candidate_id}, hash: {lc_req.candidate_artifact_hash[:8]}...",
        )

        # 9.4: AutonomousCycleConfig compatibility
        cycle_cfg = AutonomousCycleConfig(
            cycle_id="cycle-stress-001",
            symbol="BTCUSDT",
            bundle_hash=cand3.bundle_hash,
            dataset_registry_hash=cand3.dataset_registry_hash,
            qualification_policy=WalkForwardQualificationPolicy(
                policy_id="wf-policy-1",
                minimum_windows=2,
                minimum_trades=5,
                minimum_profit_factor=Decimal("1.1"),
                maximum_drawdown_pct=Decimal("15.0"),
                minimum_average_return_pct=Decimal("0.5"),
            ),
            artifact_root=tmp_base,
        )
        passed_9_4 = (
            fb.bundle_hash == cycle_cfg.bundle_hash
            and fb.dataset_registry_hash == cycle_cfg.dataset_registry_hash
            and fb.candidate_id == cand3.candidate_id
        )
        record(
            "9.4_autonomous_cycle_scope_and_config_compatibility",
            passed_9_4,
            f"Symbol: {cycle_cfg.symbol}, bundle_hash match: {fb.bundle_hash == cycle_cfg.bundle_hash}",
        )


    return results


if __name__ == "__main__":
    print("=" * 70)
    print("STARTING EMPIRICAL CHALLENGER STRESS TESTS")
    print("=" * 70)
    results = run_all_stress_tests()
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    print("=" * 70)
    print(f"STRESS TEST SUMMARY: Total={total}, Passed={passed}, Failed={failed}")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)
    sys.exit(0)
