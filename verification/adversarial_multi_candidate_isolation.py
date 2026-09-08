# Adversarial Multi-Candidate Isolation Test Suite
# Author: teamwork_preview_challenger_m1_it2_1
# Focus: Comprehensive empirical verification of multi-candidate isolation in FeedbackExtractor

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.feedback_extractor import (  # noqa: E402
    PaperQualificationPolicy,
    extract_paper_feedback,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
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
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def create_synthetic_db(
    storage_dir: Path,
    trades: list[dict[str, Any]],
    lifecycle_marks: list[dict[str, Any]] | None = None,
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
            (?, "open", ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)
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
                (?, "close", ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                """
                INSERT INTO paper_lifecycle_marks VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    i,
                    mark["candidate_id"],
                    mark["candidate_artifact_hash"],
                    mark["trade_id"],
                    mark["marked_at"],
                    json.dumps(mark.get("payload", {})),
                ),
            )
    conn_lc.commit()
    conn_lc.close()

    return ledger_path


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        tag = "[PASS]" if passed else "[FAIL]"
        results.append((name, passed, detail))
        print(f"{tag} {name}: {detail}")

    tmp_dir = tempfile.TemporaryDirectory()
    base_path = Path(tmp_dir.name)

    t0 = datetime(2026, 9, 8, 0, 0, 0, tzinfo=UTC)
    default_policy = PaperQualificationPolicy(
        paper_trades_min=5,
        paper_net_pnl_min=Decimal("0.00"),
        paper_profit_factor_min=Decimal("1.05"),
        paper_win_rate_min=Decimal("40.00"),
        paper_drawdown_max=Decimal("15.00"),
    )

    print("=" * 70)
    print("STARTING ADVERSARIAL MULTI-CANDIDATE ISOLATION STRESS TESTS")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # Scenario 1: Chronologically Interleaved Execution
    # -------------------------------------------------------------------------
    cand_alpha = build_candidate("cand-interleave-alpha-win", "BTCUSDT")
    cand_beta = build_candidate("cand-interleave-beta-loss", "BTCUSDT")
    cand_gamma = build_candidate("cand-interleave-gamma-be", "BTCUSDT")

    interleaved_trades: list[dict[str, Any]] = []
    for round_idx in range(10):
        # alpha: win +$50
        interleaved_trades.append(
            {
                "trade_id": f"trade-alpha-{round_idx}",
                "candidate_id": cand_alpha.candidate_id,
                "candidate_artifact_hash": cand_alpha.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "52000.00",
                "opened_at": (t0 + timedelta(minutes=round_idx * 30)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=round_idx * 30 + 5)).isoformat(),
                "gross_pnl": "50.00",
                "net_pnl": "50.00",
            }
        )
        # beta: loss -$50
        interleaved_trades.append(
            {
                "trade_id": f"trade-beta-{round_idx}",
                "candidate_id": cand_beta.candidate_id,
                "candidate_artifact_hash": cand_beta.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "48000.00",
                "opened_at": (t0 + timedelta(minutes=round_idx * 30 + 10)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=round_idx * 30 + 15)).isoformat(),
                "gross_pnl": "-50.00",
                "net_pnl": "-50.00",
            }
        )
        # gamma: alternating win +$20, loss -$20
        pnl = "20.00" if round_idx % 2 == 0 else "-20.00"
        exit_p = "51000.00" if round_idx % 2 == 0 else "49000.00"
        interleaved_trades.append(
            {
                "trade_id": f"trade-gamma-{round_idx}",
                "candidate_id": cand_gamma.candidate_id,
                "candidate_artifact_hash": cand_gamma.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": exit_p,
                "opened_at": (t0 + timedelta(minutes=round_idx * 30 + 20)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=round_idx * 30 + 25)).isoformat(),
                "gross_pnl": pnl,
                "net_pnl": pnl,
            }
        )

    db_interleaved = create_synthetic_db(base_path / "scenario1", interleaved_trades)

    # 1.1 Direct extraction for alpha (should be None: all wins)
    fb_alpha = extract_paper_feedback(
        ledger_path=db_interleaved,
        candidate_artifact=cand_alpha,
        policy=default_policy,
    )
    record(
        "1.1_interleaved_alpha_winner_returns_none",
        fb_alpha is None,
        f"Expected None, got {fb_alpha}",
    )

    # 1.2 Direct extraction for beta (should breach 4 gates: all losses)
    fb_beta = extract_paper_feedback(
        ledger_path=db_interleaved,
        candidate_artifact=cand_beta,
        policy=default_policy,
    )
    p1_2 = (
        fb_beta is not None
        and fb_beta.candidate_id == cand_beta.candidate_id
        and len(fb_beta.failed_gates) == 4
        and [g.gate_id for g in fb_beta.failed_gates]
        == [
            "paper_drawdown_max",
            "paper_net_pnl_min",
            "paper_profit_factor_min",
            "paper_win_rate_min",
        ]
    )
    record(
        "1.2_interleaved_beta_loser_breaches_all_4_gates",
        p1_2,
        f"Failed gates: {[g.gate_id for g in fb_beta.failed_gates] if fb_beta else None}",
    )

    # 1.3 Direct extraction for gamma (breakeven with alternating +20/-20:
    # PF=1.00 < 1.05 and DD=16.6667% > 15.00% -> exactly 2 failed gates)
    fb_gamma = extract_paper_feedback(
        ledger_path=db_interleaved,
        candidate_artifact=cand_gamma,
        policy=default_policy,
    )
    p1_3 = (
        fb_gamma is not None
        and fb_gamma.candidate_id == cand_gamma.candidate_id
        and len(fb_gamma.failed_gates) == 2
        and [g.gate_id for g in fb_gamma.failed_gates]
        == ["paper_drawdown_max", "paper_profit_factor_min"]
        and fb_gamma.failed_gates[0].observed == Decimal("16.6667")
        and fb_gamma.failed_gates[1].observed == Decimal("1.00")
    )
    dd_obs = (
        fb_gamma.failed_gates[0].observed if (fb_gamma and len(fb_gamma.failed_gates) > 0) else None
    )
    pf_obs = (
        fb_gamma.failed_gates[1].observed if (fb_gamma and len(fb_gamma.failed_gates) > 1) else None
    )
    gamma_gates_str = [g.gate_id for g in fb_gamma.failed_gates] if fb_gamma else None
    record(
        "1.3_interleaved_gamma_breakeven_isolated_exact_gates",
        p1_3,
        f"Failed gates: {gamma_gates_str}, DD: {dd_obs}, PF: {pf_obs}",
    )

    # 1.4 Symbol-only extraction (symbol=BTCUSDT)
    # Last trade in ledger is trade-gamma-9 -> resolves to cand_gamma
    fb_sym = extract_paper_feedback(
        ledger_path=db_interleaved,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        policy=default_policy,
    )
    p1_4 = (
        fb_sym is not None
        and fb_sym.candidate_id == cand_gamma.candidate_id
        and len(fb_sym.failed_gates) == 2
        and [g.gate_id for g in fb_sym.failed_gates]
        == [
            "paper_drawdown_max",
            "paper_profit_factor_min",
        ]
        and fb_sym.failed_gates[0].observed == Decimal("16.6667")
        and fb_sym.failed_gates[1].observed == Decimal("1.00")
    )
    sym_gates_str = [g.gate_id for g in fb_sym.failed_gates] if fb_sym else None
    record(
        "1.4_interleaved_symbol_only_resolves_to_latest_gamma_isolated",
        p1_4,
        f"Resolved candidate: {fb_sym.candidate_id if fb_sym else None}, failed: {sym_gates_str}",
    )

    # 1.5 Add 1 new trade for alpha at the end -> symbol-only now resolves to alpha (all wins)
    trades_with_alpha_end = list(interleaved_trades)
    trades_with_alpha_end.append(
        {
            "trade_id": "trade-alpha-final",
            "candidate_id": cand_alpha.candidate_id,
            "candidate_artifact_hash": cand_alpha.artifact_hash,
            "symbol": "BTCUSDT",
            "entry_price": "50000.00",
            "exit_price": "55000.00",
            "opened_at": (t0 + timedelta(minutes=310)).isoformat(),
            "closed_at": (t0 + timedelta(minutes=315)).isoformat(),
            "gross_pnl": "50.00",
            "net_pnl": "50.00",
        }
    )
    db_alpha_end = create_synthetic_db(base_path / "scenario1_alpha_end", trades_with_alpha_end)
    fb_alpha_end = extract_paper_feedback(
        ledger_path=db_alpha_end,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        policy=default_policy,
    )
    record(
        "1.5_interleaved_symbol_only_resolves_to_new_alpha_returns_none",
        fb_alpha_end is None,
        f"Expected None, got {fb_alpha_end}",
    )

    # -------------------------------------------------------------------------
    # Scenario 2: Multi-Symbol & Multi-Candidate Matrix
    # -------------------------------------------------------------------------
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    candidates: dict[str, tuple[CreatorCandidateArtifact, CreatorCandidateArtifact]] = {}
    matrix_trades: list[dict[str, Any]] = []

    m_time = t0
    for sym in symbols:
        c_win = build_candidate(f"cand-{sym.lower()}-winner", sym)
        c_loss = build_candidate(f"cand-{sym.lower()}-loser", sym)
        candidates[sym] = (c_win, c_loss)

        # 5 winning trades for c_win
        for i in range(5):
            m_time += timedelta(minutes=10)
            matrix_trades.append(
                {
                    "trade_id": f"{sym}-win-{i}",
                    "candidate_id": c_win.candidate_id,
                    "candidate_artifact_hash": c_win.artifact_hash,
                    "symbol": sym,
                    "entry_price": "1000.00",
                    "exit_price": "1100.00",
                    "opened_at": m_time.isoformat(),
                    "closed_at": (m_time + timedelta(minutes=5)).isoformat(),
                    "gross_pnl": "100.00",
                    "net_pnl": "100.00",
                }
            )
        # 5 losing trades for c_loss
        for i in range(5):
            m_time += timedelta(minutes=10)
            matrix_trades.append(
                {
                    "trade_id": f"{sym}-loss-{i}",
                    "candidate_id": c_loss.candidate_id,
                    "candidate_artifact_hash": c_loss.artifact_hash,
                    "symbol": sym,
                    "entry_price": "1000.00",
                    "exit_price": "900.00",
                    "opened_at": m_time.isoformat(),
                    "closed_at": (m_time + timedelta(minutes=5)).isoformat(),
                    "gross_pnl": "-100.00",
                    "net_pnl": "-100.00",
                }
            )

    db_matrix = create_synthetic_db(base_path / "scenario2_matrix", matrix_trades)

    # 2.1 Verify each winner candidate on its symbol returns None
    all_winners_ok = True
    for sym, (c_w, _) in candidates.items():
        fb_w = extract_paper_feedback(
            ledger_path=db_matrix,
            candidate_artifact=c_w,
            symbol=sym,
            policy=default_policy,
        )
        if fb_w is not None:
            all_winners_ok = False
            break
    record(
        "2.1_multi_symbol_all_winners_isolated_return_none",
        all_winners_ok,
        "All 3 symbol winners returned None in combined 30-trade ledger",
    )

    # 2.2 Verify each loser candidate on its symbol breaches 4 gates
    all_losers_ok = True
    for sym, (_, c_l) in candidates.items():
        fb_l = extract_paper_feedback(
            ledger_path=db_matrix,
            candidate_artifact=c_l,
            symbol=sym,
            policy=default_policy,
        )
        if fb_l is None or len(fb_l.failed_gates) != 4 or fb_l.candidate_id != c_l.candidate_id:
            all_losers_ok = False
            break
    record(
        "2.2_multi_symbol_all_losers_isolated_breach_4_gates",
        all_losers_ok,
        "All 3 symbol losers breached all 4 gates without interference",
    )

    # 2.3 Symbol-only extraction on each symbol (latest trade is c_loss)
    sym_only_ok = True
    for sym, (_, c_l) in candidates.items():
        fb_s = extract_paper_feedback(
            ledger_path=db_matrix,
            symbol=sym,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            policy=default_policy,
        )
        if fb_s is None or fb_s.candidate_id != c_l.candidate_id or len(fb_s.failed_gates) != 4:
            sym_only_ok = False
            break
    record(
        "2.3_multi_symbol_symbol_only_queries_isolated_per_symbol",
        sym_only_ok,
        "BTC, ETH, SOL isolated each symbol latest candidate with zero cross-symbol leakage",
    )

    # -------------------------------------------------------------------------
    # Scenario 3: Drawdown Curve & High-Water Mark Isolation
    # -------------------------------------------------------------------------
    cand_whale = build_candidate("cand-whale-winner", "BTCUSDT")
    cand_retail = build_candidate("cand-retail-loser", "BTCUSDT")

    dd_trades = [
        # Whale trade: +$10,000
        {
            "trade_id": "whale-1",
            "candidate_id": cand_whale.candidate_id,
            "candidate_artifact_hash": cand_whale.artifact_hash,
            "symbol": "BTCUSDT",
            "entry_price": "50000.00",
            "exit_price": "60000.00",
            "opened_at": t0.isoformat(),
            "closed_at": (t0 + timedelta(minutes=10)).isoformat(),
            "gross_pnl": "10000.00",
            "net_pnl": "10000.00",
        },
        # Retail trade: -$10.00
        {
            "trade_id": "retail-1",
            "candidate_id": cand_retail.candidate_id,
            "candidate_artifact_hash": cand_retail.artifact_hash,
            "symbol": "BTCUSDT",
            "entry_price": "50000.00",
            "exit_price": "49900.00",
            "opened_at": (t0 + timedelta(minutes=20)).isoformat(),
            "closed_at": (t0 + timedelta(minutes=30)).isoformat(),
            "gross_pnl": "-10.00",
            "net_pnl": "-10.00",
        },
    ]
    db_dd = create_synthetic_db(base_path / "scenario3_dd", dd_trades)

    policy_dd = PaperQualificationPolicy(
        paper_trades_min=1,
        paper_net_pnl_min=Decimal("-100.00"),
        paper_profit_factor_min=Decimal("0.00"),
        paper_win_rate_min=Decimal("0.00"),
        paper_drawdown_max=Decimal("5.00"),
    )
    fb_retail = extract_paper_feedback(
        ledger_path=db_dd,
        candidate_artifact=cand_retail,
        policy=policy_dd,
    )
    dd_gate = (
        next((g for g in fb_retail.failed_gates if g.gate_id == "paper_drawdown_max"), None)
        if fb_retail
        else None
    )
    p3 = fb_retail is not None and dd_gate is not None and dd_gate.observed == Decimal("10.0000")
    record(
        "3.1_drawdown_equity_curve_unpolluted_by_whale_winner",
        p3,
        f"Observed drawdown: {dd_gate.observed if dd_gate else None} (expected exactly 10.0000%)",
    )

    # -------------------------------------------------------------------------
    # Scenario 4: Asymmetric Trade Counts (1 Gem Trade vs 100 Noisy Trades)
    # -------------------------------------------------------------------------
    cand_gem = build_candidate("cand-subtle-gem", "BTCUSDT")
    cand_noise = build_candidate("cand-noisy-spam", "BTCUSDT")

    asym_trades: list[dict[str, Any]] = []
    for i in range(50):
        asym_trades.append(
            {
                "trade_id": f"noise-a-{i}",
                "candidate_id": cand_noise.candidate_id,
                "candidate_artifact_hash": cand_noise.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49990.00",
                "opened_at": (t0 + timedelta(minutes=i * 5)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=i * 5 + 2)).isoformat(),
                "gross_pnl": "-1.00",
                "net_pnl": "-1.00",
            }
        )
    asym_trades.append(
        {
            "trade_id": "gem-1",
            "candidate_id": cand_gem.candidate_id,
            "candidate_artifact_hash": cand_gem.artifact_hash,
            "symbol": "BTCUSDT",
            "entry_price": "50000.00",
            "exit_price": "60000.00",
            "opened_at": (t0 + timedelta(minutes=260)).isoformat(),
            "closed_at": (t0 + timedelta(minutes=265)).isoformat(),
            "gross_pnl": "1000.00",
            "net_pnl": "1000.00",
        }
    )
    for i in range(50):
        asym_trades.append(
            {
                "trade_id": f"noise-b-{i}",
                "candidate_id": cand_noise.candidate_id,
                "candidate_artifact_hash": cand_noise.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000.00",
                "exit_price": "49990.00",
                "opened_at": (t0 + timedelta(minutes=270 + i * 5)).isoformat(),
                "closed_at": (t0 + timedelta(minutes=270 + i * 5 + 2)).isoformat(),
                "gross_pnl": "-1.00",
                "net_pnl": "-1.00",
            }
        )

    db_asym = create_synthetic_db(base_path / "scenario4_asym", asym_trades)

    policy_min1 = default_policy.model_copy(update={"paper_trades_min": 1})
    fb_gem = extract_paper_feedback(
        ledger_path=db_asym,
        candidate_artifact=cand_gem,
        policy=policy_min1,
    )
    record(
        "4.1_asymmetric_single_gem_trade_isolated_returns_none",
        fb_gem is None,
        f"Expected None, got: {fb_gem}",
    )

    fb_gem_min5 = extract_paper_feedback(
        ledger_path=db_asym,
        candidate_artifact=cand_gem,
        policy=default_policy,
    )
    p4_2 = (
        fb_gem_min5 is not None
        and len(fb_gem_min5.failed_gates) == 1
        and fb_gem_min5.failed_gates[0].gate_id == "paper_trades_min"
        and fb_gem_min5.failed_gates[0].observed == Decimal("1")
    )
    gem_obs_trades = (
        fb_gem_min5.failed_gates[0].observed if (fb_gem_min5 and fb_gem_min5.failed_gates) else None
    )
    record(
        "4.2_asymmetric_single_gem_trade_isolated_observed_trades_1",
        p4_2,
        f"Observed trades: {gem_obs_trades}",
    )

    policy_noise_check = default_policy.model_copy(update={"paper_trades_min": 105})
    fb_noise = extract_paper_feedback(
        ledger_path=db_asym,
        candidate_artifact=cand_noise,
        policy=policy_noise_check,
    )
    trades_gate_noise = (
        next((g for g in fb_noise.failed_gates if g.gate_id == "paper_trades_min"), None)
        if fb_noise
        else None
    )
    p4_3 = (
        fb_noise is not None
        and trades_gate_noise is not None
        and trades_gate_noise.observed == Decimal("100")
    )
    noise_obs_trades = trades_gate_noise.observed if trades_gate_noise else None
    record(
        "4.3_asymmetric_noise_candidate_observed_trades_exactly_100",
        p4_3,
        f"Observed noise trades: {noise_obs_trades} (expected 100, not 101)",
    )

    # -------------------------------------------------------------------------
    # Scenario 5: Candidate Artifact / Path Override vs Latest Trade
    # -------------------------------------------------------------------------
    gem_art_path = base_path / "cand_gem.json"
    gem_art_path.write_text(cand_gem.model_dump_json(indent=2), encoding="utf-8")

    fb_override_path = extract_paper_feedback(
        ledger_path=db_asym,
        candidate_artifact_path=gem_art_path,
        policy=policy_min1,
    )
    record(
        "5.1_candidate_artifact_path_overrides_latest_trade_in_ledger",
        fb_override_path is None,
        f"Expected None for gem artifact path, got: {fb_override_path}",
    )

    fb_override_id = extract_paper_feedback(
        ledger_path=db_asym,
        candidate_id=cand_gem.candidate_id,
        candidate_artifact_hash=cand_gem.artifact_hash,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        policy=policy_min1,
    )
    record(
        "5.2_explicit_candidate_id_overrides_latest_trade_in_ledger",
        fb_override_id is None,
        f"Expected None for explicit candidate_id, got: {fb_override_id}",
    )

    # -------------------------------------------------------------------------
    # Scenario 6: Lifecycle Database Coexistence
    # -------------------------------------------------------------------------
    lc_marks = [
        {
            "candidate_id": cand_alpha.candidate_id,
            "candidate_artifact_hash": cand_alpha.artifact_hash,
            "trade_id": "trade-alpha-0",
            "marked_at": t0.isoformat(),
            "payload": {"unrealized_pnl": "10.00", "mark_price": "50500.00"},
        },
        {
            "candidate_id": cand_beta.candidate_id,
            "candidate_artifact_hash": cand_beta.artifact_hash,
            "trade_id": "trade-beta-0",
            "marked_at": t0.isoformat(),
            "payload": {"unrealized_pnl": "-10.00", "mark_price": "49500.00"},
        },
    ]
    db_lc = create_synthetic_db(
        base_path / "scenario6_lc", interleaved_trades, lifecycle_marks=lc_marks
    )
    fb_lc_alpha = extract_paper_feedback(
        ledger_path=db_lc,
        candidate_artifact=cand_alpha,
        policy=default_policy,
    )
    fb_lc_beta = extract_paper_feedback(
        ledger_path=db_lc,
        candidate_artifact=cand_beta,
        policy=default_policy,
    )
    p6 = fb_lc_alpha is None and fb_lc_beta is not None and len(fb_lc_beta.failed_gates) == 4
    record(
        "6.1_lifecycle_database_coexistence_clean_extraction",
        p6,
        "Coexisting lifecycle marks did not corrupt multi-candidate extraction",
    )

    # -------------------------------------------------------------------------
    # Scenario 7: High-Concurrency Multi-Candidate Extraction Determinism
    # -------------------------------------------------------------------------
    def worker_task(cand_type: str) -> tuple[str, str | None, int]:
        if cand_type == "alpha":
            fb = extract_paper_feedback(
                ledger_path=db_interleaved,
                candidate_artifact=cand_alpha,
                policy=default_policy,
            )
            return (
                "alpha",
                None if fb is None else fb.qualification_hash,
                0 if fb is None else len(fb.failed_gates),
            )
        elif cand_type == "beta":
            fb = extract_paper_feedback(
                ledger_path=db_interleaved,
                candidate_artifact=cand_beta,
                policy=default_policy,
            )
            return (
                "beta",
                fb.qualification_hash if fb else None,
                len(fb.failed_gates) if fb else 0,
            )
        else:
            fb = extract_paper_feedback(
                ledger_path=db_interleaved,
                candidate_artifact=cand_gamma,
                policy=default_policy,
            )
            return (
                "gamma",
                fb.qualification_hash if fb else None,
                len(fb.failed_gates) if fb else 0,
            )

    work_items = ["alpha", "beta", "gamma"] * 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker_task, item) for item in work_items]
        concurrent_results = [f.result() for f in futures]

    alpha_results = [r for r in concurrent_results if r[0] == "alpha"]
    beta_results = [r for r in concurrent_results if r[0] == "beta"]
    gamma_results = [r for r in concurrent_results if r[0] == "gamma"]

    all_alpha_none = all(r[1] is None and r[2] == 0 for r in alpha_results)
    all_beta_hash_identical = (
        len({r[1] for r in beta_results}) == 1
        and beta_results[0][1] is not None
        and all(r[2] == 4 for r in beta_results)
    )
    all_gamma_hash_identical = (
        len({r[1] for r in gamma_results}) == 1
        and gamma_results[0][1] is not None
        and all(r[2] == 2 for r in gamma_results)
    )

    p7 = all_alpha_none and all_beta_hash_identical and all_gamma_hash_identical
    record(
        "7.1_concurrent_multi_candidate_extractions_deterministic",
        p7,
        f"Alpha None: {all_alpha_none}, Beta id: {all_beta_hash_identical}, "
        f"Gamma id: {all_gamma_hash_identical}",
    )

    print("=" * 70)
    passed_count = sum(1 for _, p, _ in results if p)
    total_count = len(results)
    failed_count = total_count - passed_count
    print(
        f"ADVERSARIAL STRESS TEST SUMMARY: Total={total_count}, Passed={passed_count}, "
        f"Failed={failed_count}"
    )
    print("=" * 70)

    tmp_dir.cleanup()
    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
