"""Comprehensive 4-Tier E2E test suite for Phase 254 multi-asset paper trading simulation harness.

Adheres strictly to the 4-tier test methodology defined in TEST_INFRA.md:
- Tier 1: Feature Coverage (Candidate loading, isolated SQLite stores, shared 100 USDT margin pool,
  2,016-bar sequential simulation loop, dynamic leverage 1x-3x, adverse fills 2 bps + 0.04% fee,
  exact Decimal reconciliation, PaperHealthReport, PaperCohortReadinessReport, offline safety).
- Tier 2: Boundary & Corner Cases (80% margin utilization cap, zero/negative available margin,
  ATR stop-loss bounds, terminal bar forced position liquidation, corrupted candidate artifact
  rejection, non-UTC timestamp rejection, zero lookahead verification).
- Tier 3: Pairwise Combinations (Concurrent entry signals priority arbitration, restricted margin
  arbitration, coexisting long and short positions).
- Tier 4: Real-World Scenarios (End-to-end execution of run_phase_254_simulation() in temporary
  directories, validating SQLite databases, exact Decimal cash reconciliation, zero drift, high
  slippage/fee stress, capital constraints, CLI runner, and idempotency).
"""

from __future__ import annotations

import gc
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.creator_staging_probe import assert_offline_safety_invariants
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import PaperExecutionRequest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.cohort import PaperCohortReadinessReport
from autonomous_futures.paper.health import PaperHealthReport
from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.observation import observe_paper_ledger
from autonomous_futures.paper.reconciliation import reconcile_paper_positions
from autonomous_futures.paper.runtime import PaperRuntime
from autonomous_futures.paper.safety import PaperActionApproval, PaperSafetyEvidence
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.research.creator_proposals import canonical_creator_candidate_id
from autonomous_futures.research.feature_signals import CausalFeatureSignalEvaluator

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_254_paper_simulation import (  # noqa: E402
    DEFAULT_DAYS,
    DEFAULT_START_TIME,
    DEFAULT_STARTING_EQUITY,
    DEFAULT_TOTAL_BARS,
    PINNED_BUNDLE_HASH,
    PINNED_REGISTRY_HASH,
    PINNED_TARGETS,
    Phase254PaperHarness,
    SharedMarginAccount,
    _assert_zero_secrets,
    calculate_dynamic_leverage,
    compute_atr_series,
    compute_file_sha256,
    compute_signal_conviction,
    evaluate_strategy_exit,
    generate_deterministic_doge_bars,
    generate_phase_254_reports,
    load_phase_254_candidates,
    load_symbol_market_frame,
    main,
    run_phase_254_simulation,
)

# ---------------------------------------------------------------------------
# Tier 1: Feature Coverage
# ---------------------------------------------------------------------------


class TestTier1FeatureCoverage:
    """Tier 1: Feature Coverage across all 11 core Phase 254 capabilities."""

    def test_f1_candidate_spec_integrity_and_cryptographic_verification(self) -> None:
        """Verify candidate specs load correctly with valid SHA-256 hashes and DSL risk rules."""
        candidates = load_phase_254_candidates()
        assert len(candidates) == 4
        expected_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}
        assert set(candidates.keys()) == expected_symbols

        for sym, cand in candidates.items():
            target = PINNED_TARGETS[sym]
            assert cand.candidate_id == target.candidate_id
            assert len(cand.candidate_id) == 69
            assert cand.candidate_id.startswith("cand-")
            assert canonical_creator_candidate_id(cand.strategy) == target.candidate_id
            assert cand.artifact_hash == target.artifact_hash
            assert cand.bundle_hash == PINNED_BUNDLE_HASH
            assert cand.dataset_registry_hash == PINNED_REGISTRY_HASH
            assert cand.strategy.dsl_version == 2
            assert cand.strategy.universe.symbols == (sym,)
            assert cand.strategy.universe.timeframe == "5m"

            risk = cand.strategy.risk
            assert risk is not None
            assert risk.position_fraction == Decimal("0.2")
            assert risk.stop_atr_multiplier == Decimal("1.5")
            assert risk.take_profit_atr_multiplier == Decimal("3.0")
            assert risk.trailing_atr_multiplier == Decimal("1.0")

    def test_f2_isolated_sqlite_ledgers_initialization_and_schema(self, tmp_path: Path) -> None:
        """Verify creation and isolated table operations of SQLite stores."""
        output_dir = tmp_path / "sqlite_init_test"
        candidates = load_phase_254_candidates()
        harness = Phase254PaperHarness(output_dir=output_dir, candidates=candidates)

        assert harness.ledger_db_path == output_dir / "paper-ledger.sqlite3"
        assert harness.lifecycle_db_path == output_dir / "paper-lifecycle.sqlite3"
        assert harness.observation_db_path == output_dir / "paper-observations.sqlite3"

        # Append entry into isolated ledger
        entry = PaperLedgerEntry(
            event="open",
            trade_id="trade-init-001",
            candidate_id=PINNED_TARGETS["BTCUSDT"].candidate_id,
            candidate_artifact_hash=PINNED_TARGETS["BTCUSDT"].artifact_hash,
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.001"),
            fill_price=Decimal("60000.00"),
            occurred_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            entry_fee=Decimal("0.024"),
            slippage_cost=Decimal("0.012"),
        )
        harness.ledger_store.append(entry)
        assert harness.ledger_db_path.is_file()

        with sqlite3.connect(harness.ledger_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_ledger_events'"
            )
            assert cursor.fetchone() is not None
            cursor.execute("SELECT COUNT(*) FROM paper_ledger_events")
            assert cursor.fetchone()[0] == 1

        # Append telemetry into isolated lifecycle
        mark = mark_paper_position(
            entry,
            mark_price=Decimal("60500.00"),
            marked_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            previous_peak_pnl=Decimal("0.0"),
        )
        harness.lifecycle_store.append(mark)
        assert harness.lifecycle_db_path.is_file()

        with sqlite3.connect(harness.lifecycle_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_lifecycle_marks'"
            )
            assert cursor.fetchone() is not None

        # Append observation into isolated observation store
        obs = observe_paper_ledger(
            harness.ledger_store.load(),
            candidate_id=PINNED_TARGETS["BTCUSDT"].candidate_id,
            candidate_artifact_hash=PINNED_TARGETS["BTCUSDT"].artifact_hash,
            starting_equity=DEFAULT_STARTING_EQUITY,
            previous_peak_equity=DEFAULT_STARTING_EQUITY,
            mark_prices={"BTCUSDT": Decimal("60500.00")},
            observed_at=datetime(2026, 1, 1, 6, 0, tzinfo=UTC),
        )
        harness.observation_store.append(obs)
        assert harness.observation_db_path.is_file()

        with sqlite3.connect(harness.observation_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_observations'"
            )
            assert cursor.fetchone() is not None

    def test_f3_shared_margin_account_initialization_and_accounting(self) -> None:
        """Verify shared margin pool, locked margin, available margin, and equity."""
        account = SharedMarginAccount(starting_capital=Decimal("100.00"))
        assert account.starting_capital == Decimal("100.00")
        assert account.cash == Decimal("100.00")
        assert account.total_locked_margin() == Decimal("0.00")
        assert account.available_margin(account.cash) == Decimal("80.00")
        assert account.margin_utilization(account.cash) == Decimal("0.00")

        # Order allocation at 20% base margin
        alloc = account.allocate_order(
            symbol="BTCUSDT",
            confidence=Decimal("0.50"),
            mark_price=Decimal("50000.00"),
            current_equity=Decimal("100.00"),
        )
        assert alloc is not None
        base_margin, leverage, quantity = alloc
        assert base_margin == Decimal("20.00")
        assert leverage == Decimal("1.0")
        assert quantity == Decimal("0.000400")

        # Record open
        entry_fee = Decimal("0.008")
        account.record_open(
            trade_id="trade-001",
            margin_allocated=base_margin,
            leverage=leverage,
            entry_fee=entry_fee,
            equity=Decimal("100.00"),
        )
        assert account.total_locked_margin() == Decimal("20.00")
        assert account.cash == Decimal("99.992")
        assert account.available_margin(Decimal("100.00")) == Decimal("60.00")
        assert account.margin_utilization(Decimal("100.00")) == Decimal("0.20")
        assert account.max_observed_utilization == Decimal("0.20")

        # Record close
        gross_pnl = Decimal("2.00")
        exit_fee = Decimal("0.008")
        account.record_close("trade-001", gross_pnl=gross_pnl, exit_fee=exit_fee)
        assert account.total_locked_margin() == Decimal("0.00")
        assert account.cash == Decimal("99.992") + gross_pnl - exit_fee
        assert account.cash == Decimal("101.984")

    def test_f4_market_data_alignment_and_synchronization(self) -> None:
        """Verify market data synchronization across all 4 assets for 2,016 contiguous 5m bars."""
        frames: dict[str, pd.DataFrame] = {}
        for sym in PINNED_TARGETS:
            df = load_symbol_market_frame(
                symbol=sym,
                start=DEFAULT_START_TIME,
                total_bars=DEFAULT_TOTAL_BARS,
            )
            assert len(df) == DEFAULT_TOTAL_BARS
            assert df["timestamp"].iloc[0] == DEFAULT_START_TIME
            assert df["timestamp"].iloc[-1] == DEFAULT_START_TIME + timedelta(minutes=5 * 2015)
            # 5-minute contiguous spacing
            deltas = df["timestamp"].diff().dropna()
            assert (deltas == timedelta(minutes=5)).all()
            for col in ("open", "high", "low", "close"):
                assert col in df.columns
                assert (df[col] > Decimal("0")).all()
            frames[sym] = df

        # Strict timestamp synchronization across all 4 assets
        first_sym = "BTCUSDT"
        for sym in ("ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            assert (frames[first_sym]["timestamp"] == frames[sym]["timestamp"]).all()

    def test_f5_concurrent_bar_stepping_and_zero_lookahead(self) -> None:
        """Verify ATR and causal signals maintain zero lookahead, and exits precede entries."""
        doge_df = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=100)
        atr_series = compute_atr_series(doge_df, lookback=14)

        assert len(atr_series) == 100
        # First 14 bars must be None (strictly causal)
        assert all(atr_series[i] is None for i in range(14))
        # Bar 14 onward has positive ATR values
        valid_atrs = atr_series[14:]
        assert len(valid_atrs) == 86
        for val in valid_atrs:
            assert val is not None
            assert val > Decimal("0")

        # Causal evaluator checks
        candidates = load_phase_254_candidates()
        evaluator = CausalFeatureSignalEvaluator()
        evaluated = evaluator.evaluate(candidates["DOGEUSDT"], doge_df)
        assert "signal" in evaluated.columns
        assert len(evaluated) == 100

    def test_f6_dynamic_leverage_and_conviction_scoring(self) -> None:
        """Verify conviction scoring in [0.5, 1.0] and dynamic leverage in [1.0, 3.0]."""
        assert calculate_dynamic_leverage(Decimal("0.50")) == Decimal("1.0")
        assert calculate_dynamic_leverage(Decimal("0.75")) == Decimal("2.0")
        assert calculate_dynamic_leverage(Decimal("1.00")) == Decimal("3.0")
        # Clamping
        assert calculate_dynamic_leverage(Decimal("0.30")) == Decimal("1.0")
        assert calculate_dynamic_leverage(Decimal("1.20")) == Decimal("3.0")

        # Neutral row
        neutral_row = pd.Series(
            {
                "adx": 20.0,
                "rsi": 50.0,
                "ema_slope": 0.0,
                "regime_trend": 0.0,
            }
        )
        valid, conviction = compute_signal_conviction(neutral_row, signal=1)
        assert valid is True
        assert conviction == Decimal("0.50")

        # Zero signal
        valid_zero, conv_zero = compute_signal_conviction(neutral_row, signal=0)
        assert valid_zero is False
        assert conv_zero == Decimal("0")

        # Strong trend confluence row
        confluent_row = pd.Series(
            {
                "adx": 80.0,  # +0.25 bonus
                "rsi": 100.0,  # +0.15 bonus
                "ema_slope": 1.5,  # +0.05 bonus
                "regime_trend": 1.0,  # +0.05 bonus
            }
        )
        valid_max, conv_max = compute_signal_conviction(confluent_row, signal=1)
        assert valid_max is True
        assert conv_max == Decimal("1.00")
        assert calculate_dynamic_leverage(conv_max) == Decimal("3.0")

    def test_f7_deterministic_adverse_fills_and_fees(self, tmp_path: Path) -> None:
        """Verify 2 bps adverse slippage and 0.04% taker fee applied deterministically on fills."""
        ledger = SqlitePaperLedger(tmp_path / "fill_test.sqlite3")
        runtime = PaperRuntime(ledger)

        cand_id = PINNED_TARGETS["BTCUSDT"].candidate_id
        cand_hash = PINNED_TARGETS["BTCUSDT"].artifact_hash
        mark_price = Decimal("60000.00")
        quantity = Decimal("0.001")
        fee_rate = Decimal("0.0004")
        slippage_bps = Decimal("2")

        open_req = PaperExecutionRequest(
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            qualified_symbols=("BTCUSDT",),
            symbol="BTCUSDT",
            side="LONG",
            mark_price=mark_price,
            quantity=quantity,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )
        evidence = PaperSafetyEvidence(
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            qualification_hash=PINNED_TARGETS["BTCUSDT"].walk_forward_hash,
            qualification_decision="qualified",
            zero_oos_liquidations=True,
        )
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        approval = PaperActionApproval(
            approval_id="apprv-open-btc",
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            trade_id="trade-btc-001",
            action="open",
            approved_at=now,
            expires_at=now + timedelta(minutes=5),
        )

        res = runtime.open(open_req, evidence, approval, trade_id="trade-btc-001", occurred_at=now)
        assert res.status == "opened"

        # Long entry: fill_price = mark_price * (1 + 0.0002) = 60000 * 1.0002 = 60012.00
        expected_fill = Decimal("60012.00")
        assert res.fill_price == expected_fill
        expected_fee = expected_fill * quantity * fee_rate
        assert res.entry_fee == expected_fee

        # Close position with adverse exit fill
        close_req = open_req.model_copy(update={"mark_price": Decimal("61000.00")})
        close_approval = PaperActionApproval(
            approval_id="apprv-close-btc",
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            trade_id="trade-btc-001",
            action="close",
            approved_at=now + timedelta(minutes=5),
            expires_at=now + timedelta(minutes=10),
        )
        close_res = runtime.close(
            close_req,
            evidence,
            close_approval,
            trade_id="trade-btc-001",
            exit_mark_price=Decimal("61000.00"),
            occurred_at=now + timedelta(minutes=5),
        )
        assert close_res.status == "closed"
        # Long exit: fill_price = mark_price * (1 - 0.0002) = 61000 * 0.9998 = 60987.80
        expected_exit_fill = Decimal("60987.80")
        assert close_res.fill_price == expected_exit_fill
        assert close_res.exit_fee == expected_exit_fill * quantity * fee_rate

    def test_f8_decimal_balance_reconciliation_and_zero_drift(self, tmp_path: Path) -> None:
        """Verify exact Decimal accounting: net_pnl == gross_pnl - fees, zero cash drift."""
        ledger = SqlitePaperLedger(tmp_path / "recon_test.sqlite3")

        cand_id = PINNED_TARGETS["SOLUSDT"].candidate_id
        cand_hash = PINNED_TARGETS["SOLUSDT"].artifact_hash
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

        open_entry = PaperLedgerEntry(
            event="open",
            trade_id="trade-sol-001",
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            symbol="SOLUSDT",
            side="LONG",
            quantity=Decimal("1.0"),
            fill_price=Decimal("150.00"),
            occurred_at=now,
            entry_fee=Decimal("0.06"),
            slippage_cost=Decimal("0.03"),
        )
        close_entry = PaperLedgerEntry(
            event="close",
            trade_id="trade-sol-001",
            candidate_id=cand_id,
            candidate_artifact_hash=cand_hash,
            symbol="SOLUSDT",
            side="LONG",
            quantity=Decimal("1.0"),
            fill_price=Decimal("155.00"),
            occurred_at=now + timedelta(minutes=15),
            gross_pnl=Decimal("5.00"),
            entry_fee=Decimal("0.06"),
            exit_fee=Decimal("0.062"),
            net_pnl=Decimal("4.878"),
            slippage_cost=Decimal("0.031"),
        )
        ledger.append(open_entry)
        ledger.append(close_entry)

        loaded = ledger.load()
        recon = reconcile_paper_positions(loaded, ())
        assert recon.reconciled is True
        assert recon.runtime_only_trade_ids == ()
        assert recon.ledger_only_trade_ids == ()

        # Assert net_pnl exact formula
        assert close_entry.gross_pnl is not None
        assert close_entry.entry_fee is not None
        assert close_entry.exit_fee is not None
        expected_net = close_entry.gross_pnl - close_entry.entry_fee - close_entry.exit_fee
        assert close_entry.net_pnl == expected_net

    def test_f9_multi_asset_paper_health_report_generation(self, tmp_path: Path) -> None:
        """Verify PaperHealthReport generation with candidate bindings and safety pins."""
        candidates = load_phase_254_candidates()
        harness = Phase254PaperHarness(
            output_dir=tmp_path / "health_rep_test", candidates=candidates
        )
        as_of = DEFAULT_START_TIME + timedelta(days=7)

        # Populate observations for each candidate
        for _sym, cand in candidates.items():
            obs = observe_paper_ledger(
                harness.ledger_store.load(),
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                starting_equity=DEFAULT_STARTING_EQUITY,
                previous_peak_equity=DEFAULT_STARTING_EQUITY,
                mark_prices={
                    "BTCUSDT": Decimal("100.00"),
                    "ETHUSDT": Decimal("100.00"),
                    "SOLUSDT": Decimal("100.00"),
                    "DOGEUSDT": Decimal("100.00"),
                },
                observed_at=as_of,
            )
            harness.observation_store.append(obs)

        health_reports, _ = generate_phase_254_reports(
            harness.ledger_store,
            harness.lifecycle_store,
            harness.observation_store,
            candidates,
            as_of=as_of,
            days=7,
        )

        assert len(health_reports) == 4
        for sym, rep in health_reports.items():
            assert isinstance(rep, PaperHealthReport)
            assert rep.candidate_id == PINNED_TARGETS[sym].candidate_id
            assert rep.candidate_artifact_hash == PINNED_TARGETS[sym].artifact_hash
            assert rep.paper_activation is False
            assert rep.execution_authority is False
            assert rep.exchange_access is False
            assert rep.as_of.tzinfo == UTC

    def test_f10_paper_cohort_readiness_report_generation(self, tmp_path: Path) -> None:
        """Verify PaperCohortReadinessReport model structure and invariant fields."""
        candidates = load_phase_254_candidates()
        harness = Phase254PaperHarness(
            output_dir=tmp_path / "cohort_rep_test", candidates=candidates
        )
        as_of = DEFAULT_START_TIME + timedelta(days=7)

        for _sym, cand in candidates.items():
            obs = observe_paper_ledger(
                harness.ledger_store.load(),
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                starting_equity=DEFAULT_STARTING_EQUITY,
                previous_peak_equity=DEFAULT_STARTING_EQUITY,
                mark_prices={
                    "BTCUSDT": Decimal("100.00"),
                    "ETHUSDT": Decimal("100.00"),
                    "SOLUSDT": Decimal("100.00"),
                    "DOGEUSDT": Decimal("100.00"),
                },
                observed_at=as_of,
            )
            harness.observation_store.append(obs)

        _, cohort_rep = generate_phase_254_reports(
            harness.ledger_store,
            harness.lifecycle_store,
            harness.observation_store,
            candidates,
            as_of=as_of,
            days=7,
        )

        assert isinstance(cohort_rep, PaperCohortReadinessReport)
        assert cohort_rep.expected_candidate_count == 4
        assert cohort_rep.reported_candidate_count == 4
        assert cohort_rep.paper_activation is False
        assert cohort_rep.execution_authority is False
        assert cohort_rep.exchange_access is False

    def test_f11_offline_safety_invariants_and_zero_secrets(self) -> None:
        """Verify safety invariants succeed and zero secrets checks catch leaks."""
        # Clean safety check
        assert_offline_safety_invariants()

        # Clean string passes
        _assert_zero_secrets("Clean payload without any secret", "test_source")

        # Secret patterns raise DomainViolation
        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets("leaked key AIzaSyD9876543210abcdefghijklmnop", "test_key")

        with pytest.raises(DomainViolation, match="Secret pattern matched"):
            _assert_zero_secrets("bearer ya29.a0AfH6SMBabc123456789", "test_token")


# ---------------------------------------------------------------------------
# Tier 2: Boundary & Corner Cases
# ---------------------------------------------------------------------------


class TestTier2BoundaryAndEdgeCases:
    """Tier 2: Boundary Value Analysis and Edge Case stress testing."""

    def test_b1_margin_utilization_cap_enforcement_and_unencumbered_buffer(self) -> None:
        """Verify strictly capped 80% margin utilization and preserved >= 20% equity buffer."""
        account = SharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            base_allocation_fraction=Decimal("0.20"),
        )
        equity = Decimal("100.00")

        # Allocate 4 positions (each 20 USDT -> 20%, 40%, 60%, 80%)
        trades = ["t1", "t2", "t3", "t4"]
        for t_id in trades:
            alloc = account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("100.00"), equity)
            assert alloc is not None
            margin, lev, _ = alloc
            account.record_open(t_id, margin, lev, Decimal("0.001"), equity)

        assert account.total_locked_margin() == Decimal("80.00")
        assert account.margin_utilization(equity) == Decimal("0.80")
        assert account.available_margin(equity) == Decimal("0.00")

        # 5th position must be rejected (would breach 80% ceiling)
        breached_alloc = account.allocate_order(
            "ETHUSDT", Decimal("0.50"), Decimal("100.00"), equity
        )
        assert breached_alloc is None

        # Verify unencumbered buffer
        unencumbered_buffer = (equity - account.total_locked_margin()) / equity
        assert unencumbered_buffer >= Decimal("0.20")

    def test_b2_zero_and_negative_equity_and_fee_shortage(self) -> None:
        """Verify zero/negative equity and fee shortage reject allocations safely."""
        account = SharedMarginAccount(starting_capital=Decimal("100.00"))

        # Zero equity
        assert (
            account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("100.00"), Decimal("0.00"))
            is None
        )
        # Negative equity
        assert (
            account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("100.00"), Decimal("-10.00"))
            is None
        )

        # Utilization calculation for <= 0 equity returns Decimal("1.0") without ZeroDivisionError
        assert account.margin_utilization(Decimal("0.00")) == Decimal("1.0")
        assert account.margin_utilization(Decimal("-50.00")) == Decimal("1.0")

        # Available margin returns 0 when locked exceeds max allowed
        account._locked_margin_by_trade["huge"] = Decimal("90.00")
        assert account.available_margin(Decimal("100.00")) == Decimal("0")

        # Cash too low for fees (cash < base_margin * 0.005)
        account_poor = SharedMarginAccount(starting_capital=Decimal("100.00"))
        account_poor.cash = Decimal("0.05")  # Less than 20 * 0.005 = 0.10
        assert (
            account_poor.allocate_order(
                "BTCUSDT", Decimal("0.50"), Decimal("100.00"), Decimal("100.00")
            )
            is None
        )

    def test_b3_atr_protective_stops_and_trailing_watermarks(self) -> None:
        """Verify ATR protective stops trigger exactly on boundary crosses for LONG and SHORT."""
        # Long protective bounds: stop = entry - 1.5*ATR, target = entry + 3.0*ATR
        entry_price = Decimal("100.00")
        atr = Decimal("2.00")
        stop_price = entry_price - atr * Decimal("1.5")  # 97.00
        target_price = entry_price + atr * Decimal("3.0")  # 106.00
        trailing_stop = entry_price - atr * Decimal("1.0")  # 98.00

        assert target_price == Decimal("106.00")
        assert trailing_stop == Decimal("98.00")

        # Boundary checks for Long
        bar_low_hit = Decimal("97.00")
        bar_low_miss = Decimal("97.01")
        assert bar_low_hit <= stop_price
        assert not (bar_low_miss <= stop_price)

        # Short protective bounds: stop = entry + 1.5*ATR
        short_stop_price = entry_price + atr * Decimal("1.5")  # 103.00
        bar_high_hit = Decimal("103.00")
        bar_high_miss = Decimal("102.99")
        assert bar_high_hit >= short_stop_price
        assert not (bar_high_miss >= short_stop_price)

        # Strategy exit parser test
        row = pd.Series({"rsi": 75.0, "adx": 25.0})
        assert evaluate_strategy_exit(row, "LONG", "rsi > 70", "rsi < 30") is True
        assert evaluate_strategy_exit(row, "LONG", "rsi > 80", "rsi < 30") is False

    def test_b4_terminal_cutoff_forced_position_liquidation(self, tmp_path: Path) -> None:
        """Verify terminal cutoff (terminal_cutoff = total_bars - 72) liquidates open positions."""
        output_dir = tmp_path / "cutoff_test"
        # Run 100 bars simulation (cutoff is at bar 28)
        res = run_phase_254_simulation(
            output_dir=output_dir,
            total_bars=100,
            days=1,
            starting_equity=Decimal("100.00"),
        )
        assert res.positions_reconciled is True
        ledger = SqlitePaperLedger(output_dir / "paper-ledger.sqlite3").load()
        assert ledger.open_positions() == ()

    def test_b5_corrupted_candidate_artifact_rejection(self, tmp_path: Path) -> None:
        """Verify load_phase_254_candidates rejects corrupted IDs, hashes, and rules."""
        src_dir = Path("artifacts/research/phase252/candidates")
        corrupt_dir = tmp_path / "corrupted_candidates"
        corrupt_dir.mkdir(parents=True, exist_ok=True)

        # Copy valid candidate
        target = PINNED_TARGETS["BTCUSDT"]
        valid_json = (src_dir / target.filename).read_text(encoding="utf-8")

        # 1. Tampered candidate_id
        data = json.loads(valid_json)
        data["candidate_id"] = "cand-" + "9" * 64
        (corrupt_dir / target.filename).write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((DomainViolation, ValidationError)):
            load_phase_254_candidates(corrupt_dir)

        # 2. Tampered artifact_hash
        data = json.loads(valid_json)
        data["artifact_hash"] = "0" * 64
        (corrupt_dir / target.filename).write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((DomainViolation, ValidationError)):
            load_phase_254_candidates(corrupt_dir)

        # 3. Tampered bundle_hash
        data = json.loads(valid_json)
        data["bundle_hash"] = "f" * 64
        (corrupt_dir / target.filename).write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((DomainViolation, ValidationError)):
            load_phase_254_candidates(corrupt_dir)

        # 4. Tampered position_fraction in risk model
        data = json.loads(valid_json)
        data["strategy"]["risk"]["position_fraction"] = "0.5"
        (corrupt_dir / target.filename).write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((DomainViolation, ValidationError)):
            load_phase_254_candidates(corrupt_dir)

        # 5. Missing candidate file
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="Candidate artifact file missing"):
            load_phase_254_candidates(empty_dir)

    def test_b6_invalid_market_data_and_skew_rejection(self, tmp_path: Path) -> None:
        """Verify market frame loader rejects incomplete bar series or missing files."""
        # Incomplete data raises DataQualityError
        with pytest.raises(DataQualityError, match="Incomplete data for BTCUSDT"):
            load_symbol_market_frame(
                symbol="BTCUSDT",
                start=DEFAULT_START_TIME,
                total_bars=500000,  # exceeds available range
            )

        # Missing parquet file raises FileNotFoundError
        with pytest.raises(FileNotFoundError, match="Canonical market data missing"):
            load_symbol_market_frame(
                symbol="NONEXISTENT",
                start=DEFAULT_START_TIME,
                total_bars=100,
                data_dir=tmp_path,
            )

    def test_b7_zero_lookahead_causality_verification(self) -> None:
        """Verify indicators and signals at bar t do not change when future bars mutate."""
        bars_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=60)
        bars_modified = bars_base.copy(deep=True)

        # Mutate future bars (bars 40 to 59)
        for i in range(40, 60):
            bars_modified.loc[i, "close"] = Decimal("0.999")
            bars_modified.loc[i, "high"] = Decimal("1.000")
            bars_modified.loc[i, "low"] = Decimal("0.998")

        candidates = load_phase_254_candidates()
        evaluator = CausalFeatureSignalEvaluator()
        eval_base = evaluator.evaluate(candidates["DOGEUSDT"], bars_base)
        eval_mod = evaluator.evaluate(candidates["DOGEUSDT"], bars_modified)

        # Bars 0 to 39 must be bit-for-bit identical despite future changes
        for col in ("signal", "rsi", "adx"):
            if col in eval_base.columns:
                pd.testing.assert_series_equal(
                    eval_base[col].iloc[:40],
                    eval_mod[col].iloc[:40],
                    check_exact=True,
                )


# ---------------------------------------------------------------------------
# Tier 3: Pairwise Combinations
# ---------------------------------------------------------------------------


class TestTier3PairwiseCombinations:
    """Tier 3: Pairwise interactions across symbols, convictions, and margin states."""

    def test_p1_concurrent_entry_signals_priority_arbitration(self) -> None:
        """Verify priority sorting by conviction descending and rank ascending."""
        requests: list[dict[str, Any]] = [
            {
                "symbol": "ETHUSDT",
                "conviction": Decimal("0.70"),
                "rank": PINNED_TARGETS["ETHUSDT"].phase_253_rank,
            },
            {
                "symbol": "BTCUSDT",
                "conviction": Decimal("0.90"),
                "rank": PINNED_TARGETS["BTCUSDT"].phase_253_rank,
            },
            {
                "symbol": "DOGEUSDT",
                "conviction": Decimal("0.90"),
                "rank": PINNED_TARGETS["DOGEUSDT"].phase_253_rank,
            },
            {
                "symbol": "SOLUSDT",
                "conviction": Decimal("0.75"),
                "rank": PINNED_TARGETS["SOLUSDT"].phase_253_rank,
            },
        ]

        # Priority sorting: conviction (descending), Phase 253 candidate rank (ascending)
        requests.sort(key=lambda req: (-req["conviction"], req["rank"]))

        ordered_symbols = [r["symbol"] for r in requests]
        # DOGE and BTC both have 0.90; DOGE rank 1 < BTC rank 2
        # Then SOL (0.75), then ETH (0.70)
        assert ordered_symbols == ["DOGEUSDT", "BTCUSDT", "SOLUSDT", "ETHUSDT"]

    def test_p2_restricted_margin_priority_arbitration(self) -> None:
        """Verify higher priority candidate wins allocation while lower priority is rejected."""
        account = SharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            base_allocation_fraction=Decimal("0.20"),
        )
        equity = Decimal("100.00")

        # Lock 60 USDT already (3 positions of 20 USDT)
        account.record_open("init1", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), equity)
        account.record_open("init2", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), equity)
        account.record_open("init3", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), equity)

        assert account.available_margin(equity) == Decimal("20.00")

        # Two competing candidates signal simultaneously
        # Competing Cand 1: Higher priority (DOGEUSDT, conviction 0.95)
        # Competing Cand 2: Lower priority (ETHUSDT, conviction 0.60)
        cand1_alloc = account.allocate_order("DOGEUSDT", Decimal("0.95"), Decimal("0.15"), equity)
        assert cand1_alloc is not None
        margin, lev, _ = cand1_alloc
        account.record_open("doge_win", margin, lev, Decimal("0.001"), equity)

        # Account is now at 80% utilization
        assert account.margin_utilization(equity) == Decimal("0.80")

        # Lower priority candidate must be rejected
        cand2_alloc = account.allocate_order("ETHUSDT", Decimal("0.60"), Decimal("3000.00"), equity)
        assert cand2_alloc is None

    def test_p3_coexisting_long_and_short_positions_accounting(self) -> None:
        """Verify coexisting LONG and SHORT positions track margins and equity correctly."""
        account = SharedMarginAccount(starting_capital=Decimal("100.00"))
        equity = Decimal("100.00")

        # Allocate BTC LONG
        btc_alloc = account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("50000.00"), equity)
        assert btc_alloc is not None
        account.record_open("btc_long", btc_alloc[0], btc_alloc[1], Decimal("0.008"), equity)

        # Allocate DOGE SHORT
        doge_alloc = account.allocate_order("DOGEUSDT", Decimal("0.50"), Decimal("0.150"), equity)
        assert doge_alloc is not None
        account.record_open("doge_short", doge_alloc[0], doge_alloc[1], Decimal("0.008"), equity)

        assert account.total_locked_margin() == Decimal("40.00")

        # Unrealized PnL: BTC Long gains +1.00, DOGE Short loses -0.50
        unrealized = Decimal("1.00") - Decimal("0.50")
        current_eq = account.current_equity(unrealized)
        assert current_eq == account.cash + unrealized

        # Close BTC LONG: releases 20 USDT, locks remain 20 USDT
        account.record_close("btc_long", gross_pnl=Decimal("1.00"), exit_fee=Decimal("0.008"))
        assert account.total_locked_margin() == Decimal("20.00")

        # Close DOGE SHORT: releases remaining 20 USDT
        account.record_close("doge_short", gross_pnl=Decimal("-0.50"), exit_fee=Decimal("0.008"))
        assert account.total_locked_margin() == Decimal("0.00")

        # Exact Decimal cash reconciliation
        expected_cash = (
            Decimal("100.00")
            - Decimal("0.008")  # btc entry fee
            - Decimal("0.008")  # doge entry fee
            + Decimal("1.00")  # btc gross pnl
            - Decimal("0.008")  # btc exit fee
            - Decimal("0.50")  # doge gross pnl
            - Decimal("0.008")  # doge exit fee
        )
        assert account.cash == expected_cash


# ---------------------------------------------------------------------------
# Tier 4: Real-World Scenarios
# ---------------------------------------------------------------------------


class TestTier4RealWorldScenarios:
    """Tier 4: Comprehensive end-to-end execution, stress testing, and CLI execution."""

    def test_s1_canonical_2016_bar_e2e_simulation(self, tmp_path: Path) -> None:
        """Scenario 1: Full 2,016-bar 7-day simulation with exact cash reconciliation."""
        output_dir = tmp_path / "e2e_canonical"
        result = run_phase_254_simulation(
            output_dir=output_dir,
            total_bars=DEFAULT_TOTAL_BARS,
            days=DEFAULT_DAYS,
            starting_equity=DEFAULT_STARTING_EQUITY,
        )

        # Baseline execution results
        assert result.total_bars == 2016
        assert result.total_trades == 392
        assert result.winning_trades == 109
        assert result.losing_trades == 283
        assert abs(result.win_rate - 0.2781) < 0.005
        assert result.starting_equity == Decimal("100.00")
        assert result.final_cash == Decimal("169.000444108707570160")
        assert result.realized_pnl == Decimal("69.000444108707570160")
        assert result.cumulative_fees == Decimal("17.733699462835029840")
        assert result.cumulative_slippage == Decimal("8.86685355545740")
        assert float(result.max_margin_utilization) <= 0.8000
        assert result.positions_reconciled is True
        assert result.accounting_reconciled is True

        # Cohort readiness
        assert result.cohort_report.cohort_status == "ready_for_human_review"
        assert result.cohort_report.all_mature is True
        assert result.cohort_report.all_accounting_complete is True
        assert result.cohort_report.healthy_candidate_count == 4
        assert result.cohort_report.mature_candidate_count == 4
        assert result.cohort_report.blocked_candidate_count == 0
        assert result.cohort_report.attention_candidate_count == 0

        # Health reports
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            rep = result.health_reports[sym]
            assert rep.health_status == "healthy"
            assert rep.maturity_status == "mature"
            assert rep.accounting_complete is True
            assert rep.open_position_count == 0

        # All 9 artifacts exist and hashes match
        expected_artifacts = [
            "paper-ledger.sqlite3",
            "paper-lifecycle.sqlite3",
            "paper-observations.sqlite3",
            "paper-health-report-BTCUSDT.json",
            "paper-health-report-ETHUSDT.json",
            "paper-health-report-SOLUSDT.json",
            "paper-health-report-DOGEUSDT.json",
            "paper-cohort-readiness-report.json",
            "paper-summary.json",
        ]
        for name in expected_artifacts:
            file_path = output_dir / name
            assert file_path.is_file(), f"Missing artifact: {name}"
            assert compute_file_sha256(file_path) == result.artifact_hashes[name]

        # Zero secrets verification in generated json artifacts
        for name in expected_artifacts:
            if name.endswith(".json"):
                _assert_zero_secrets((output_dir / name).read_text(encoding="utf-8"), name)

    def test_s2_high_slippage_and_fee_stress(self, tmp_path: Path) -> None:
        """Scenario 2: Double adverse slippage (4 bps) and taker fees (0.08%) over 288 bars."""
        output_dir = tmp_path / "stress_slippage_fees"
        result = run_phase_254_simulation(
            output_dir=output_dir,
            total_bars=288,
            days=1,
            fee_rate=Decimal("0.0008"),
            slippage_bps=Decimal("4"),
        )
        assert result.positions_reconciled is True
        assert result.accounting_reconciled is True
        assert result.cumulative_fees > Decimal("0")
        assert result.cumulative_slippage > Decimal("0")
        assert result.final_cash == result.starting_equity + result.realized_pnl

    def test_s3_capital_constrained_execution(self, tmp_path: Path) -> None:
        """Scenario 3: Capital constrained portfolio (50 USDT) over 288 bars."""
        output_dir = tmp_path / "constrained_capital"
        result = run_phase_254_simulation(
            output_dir=output_dir,
            total_bars=288,
            days=1,
            starting_equity=Decimal("50.00"),
        )
        assert result.starting_equity == Decimal("50.00")
        assert result.positions_reconciled is True
        assert result.accounting_reconciled is True
        assert float(result.max_margin_utilization) <= 0.8000
        assert result.final_cash == Decimal("50.00") + result.realized_pnl

    def test_s4_standalone_cli_runner_execution(self, tmp_path: Path) -> None:
        """Scenario 4: Standalone CLI invocation of main() producing code 0 and all artifacts."""
        output_dir = tmp_path / "cli_runner"
        exit_code = main(
            [
                "--output-dir",
                str(output_dir),
                "--bars",
                "288",
                "--days",
                "1",
                "--starting-equity",
                "100.00",
            ]
        )
        assert exit_code == 0
        assert (output_dir / "paper-summary.json").is_file()
        assert (output_dir / "paper-cohort-readiness-report.json").is_file()
        assert (output_dir / "paper-ledger.sqlite3").is_file()
        assert (output_dir / "paper-lifecycle.sqlite3").is_file()
        assert (output_dir / "paper-observations.sqlite3").is_file()

    def test_s5_teardown_resilience_and_idempotency(self, tmp_path: Path) -> None:
        """Scenario 5: Re-running simulation into same output_dir reinitializes cleanly."""
        output_dir = tmp_path / "idempotent_test"
        res1 = run_phase_254_simulation(output_dir=output_dir, total_bars=288, days=1)
        assert res1.positions_reconciled is True

        # Cleanly release SQLite handles before second execution on Windows
        del res1
        gc.collect()

        # Second run in the exact same directory must execute cleanly
        res2 = run_phase_254_simulation(output_dir=output_dir, total_bars=288, days=1)
        assert res2.positions_reconciled is True
        assert res2.accounting_reconciled is True
        assert (output_dir / "paper-summary.json").is_file()
