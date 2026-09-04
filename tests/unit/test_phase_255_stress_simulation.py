"""Comprehensive 4-Tier E2E test suite for Phase 255 Multi-Vector Stress Simulation.

Adheres strictly to the 4-tier test methodology defined in TEST_INFRA.md:
- Tier 1: Feature Coverage (Synthetic shock injectors, adverse gap fill calculation,
  HardenedSharedMarginAccount initial state, dynamic leverage de-escalation, 3-stage
  circuit breakers, emergency position liquidation).
- Tier 2: Boundary & Corner Cases (Boundary shocks -10% and -25%, 50x slippage surge
  and 200 bps boundary, exact 80.00% margin utilization cap boundary, >= 20.00% reserve
  buffer preservation, same-candle stop-loss / take-profit priority, non-negative equity
  guarantee under extreme gap).
- Tier 3: Pairwise Combinations (Simultaneous flash crash + 50x slippage surge, concurrent
  positions under volatility halt, emergency liquidation during spread blowout, dynamic
  leverage and allocation halving under throttled regime).
- Tier 4: Real-World Scenarios (End-to-end execution of baseline, flash crash, and composite
  crisis tracks in isolated temporary stores, validation of all 6 tracks in the persisted
  summary artifact, isolated SQLite databases, offline safety invariants, CLI execution,
  and exact Decimal accounting reconciliation).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from autonomous_futures.creator_staging_probe import assert_offline_safety_invariants
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.circuit_breakers import (
    CircuitBreakerConfig,
    EmergencyLiquidationEvent,
    HardenedSharedMarginAccount,
    calculate_adverse_gap_fill,
)
from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.paper.stress_vectors import (
    MarketShockSpec,
    ShockType,
    SyntheticMarketShockInjector,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_255_stress_simulation import (  # noqa: E402
    DEFAULT_START_TIME,
    PINNED_BUNDLE_HASH,
    PINNED_REGISTRY_HASH,
    PINNED_TARGETS,
    TRACK_DEFINITIONS,
    _assert_zero_secrets,
    generate_deterministic_doge_bars,
    load_phase_255_candidates,
    load_symbol_market_frame,
    main,
    run_single_stress_track,
)

# ---------------------------------------------------------------------------
# Tier 1: Feature Coverage
# ---------------------------------------------------------------------------


class TestTier1FeatureCoverage:
    """Tier 1: Feature Coverage across Phase 255 shock vectors, margin, and circuit breakers."""

    def test_f1_market_shock_spec_validation_and_invariants(self) -> None:
        """Verify MarketShockSpec model parameters, default values, and strict validation."""
        spec = MarketShockSpec(
            shock_type=ShockType.FLASH_CRASH,
            drop_fraction=Decimal("-0.20"),
            slippage_multiplier=Decimal("50"),
            spread_multiplier=Decimal("20"),
        )
        assert spec.shock_type == ShockType.FLASH_CRASH
        assert spec.drop_fraction == Decimal("-0.20")
        assert spec.slippage_multiplier == Decimal("50")
        assert spec.spread_multiplier == Decimal("20")
        assert spec.start_bar_index == 500
        assert spec.duration_bars == 12
        assert spec.target_symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")

        # Validator: drop_fraction magnitude < 0.05 raises ValueError
        with pytest.raises(ValidationError, match="drop_fraction magnitude"):
            MarketShockSpec(shock_type=ShockType.FLASH_CRASH, drop_fraction=Decimal("-0.01"))

        # Validator: drop_fraction magnitude > 0.50 raises ValueError
        with pytest.raises(ValidationError, match="drop_fraction magnitude"):
            MarketShockSpec(shock_type=ShockType.FLASH_CRASH, drop_fraction=Decimal("-0.60"))

        # Slippage multiplier ge=1 and le=100
        with pytest.raises(ValidationError):
            MarketShockSpec(shock_type=ShockType.SLIPPAGE_SURGE, slippage_multiplier=Decimal("0"))
        with pytest.raises(ValidationError):
            MarketShockSpec(shock_type=ShockType.SLIPPAGE_SURGE, slippage_multiplier=Decimal("101"))

        # Extra fields forbidden
        with pytest.raises(ValidationError):
            MarketShockSpec.model_validate(
                {"shock_type": ShockType.FLASH_CRASH, "extra_invalid_field": True}
            )

    def test_f2_synthetic_shock_injector_flash_crash_envelope_preservation(self) -> None:
        """Verify flash crash injection modifies prices while preserving candle envelopes."""
        df_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=50)

        # 1. Full adverse drop (open, close, and low drop)
        idx = 20
        orig_open = df_base.at[idx, "open"]
        orig_close = df_base.at[idx, "close"]
        df_crashed = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=idx, drop_pct=Decimal("0.20"), wick_only=False
        )

        assert len(df_crashed) == 50
        assert df_crashed.at[idx, "open"] == orig_open * Decimal("0.80")
        assert df_crashed.at[idx, "close"] == orig_close * Decimal("0.80")
        # Invariant: high >= max(open, close) and low <= min(open, close)
        for i in range(len(df_crashed)):
            o = df_crashed.at[i, "open"]
            h = df_crashed.at[i, "high"]
            low_val = df_crashed.at[i, "low"]
            c = df_crashed.at[i, "close"]
            assert h >= max(o, c)
            assert low_val <= min(o, c)
            assert low_val > Decimal("0")

        # 2. Wick-only drop (only low plunges, open and close remain unchanged)
        df_wick = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=idx, drop_pct=Decimal("0.15"), wick_only=True
        )
        assert df_wick.at[idx, "open"] == orig_open
        assert df_wick.at[idx, "close"] == orig_close
        assert df_wick.at[idx, "low"] < df_base.at[idx, "low"]

        # Error cases: out of range start_idx or drop magnitude
        with pytest.raises(ValueError, match="out of range"):
            SyntheticMarketShockInjector.inject_flash_crash(df_base, start_idx=100, drop_pct=0.10)
        with pytest.raises(ValueError, match="drop_pct magnitude"):
            SyntheticMarketShockInjector.inject_flash_crash(df_base, start_idx=10, drop_pct=0.01)

    def test_f3_synthetic_shock_injector_slippage_and_spread_blowout(self) -> None:
        """Verify slippage surge and spread blowout annotate dataframes and attributes."""
        df_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=30)

        # Slippage surge (50x = 100 bps)
        df_slip = SyntheticMarketShockInjector.inject_slippage_surge(df_base, multiplier=50)
        assert (df_slip["slippage_multiplier"] == Decimal("50")).all()
        assert (df_slip["slippage_bps"] == Decimal("100.0")).all()
        assert df_slip.attrs["slippage_multiplier"] == Decimal("50")
        assert df_slip.attrs["slippage_bps"] == Decimal("100.0")

        # Spread blowout (20x = 40 bps)
        df_spread = SyntheticMarketShockInjector.inject_spread_blowout(df_base, multiplier=20)
        assert (df_spread["spread_multiplier"] == Decimal("20")).all()
        assert (df_spread["spread_bps"] == Decimal("40.0")).all()
        assert df_spread.attrs["spread_multiplier"] == Decimal("20")
        assert df_spread.attrs["spread_bps"] == Decimal("40.0")

        # Multiplier < 1.0 raises ValueError
        with pytest.raises(ValueError, match="multiplier must be >= 1.0"):
            SyntheticMarketShockInjector.inject_slippage_surge(df_base, multiplier=Decimal("0.5"))
        with pytest.raises(ValueError, match="multiplier must be >= 1.0"):
            SyntheticMarketShockInjector.inject_spread_blowout(df_base, multiplier=Decimal("0.9"))

    def test_f4_synthetic_shock_injector_whipsaws_and_composite_crisis(self) -> None:
        """Verify whipsaw and composite crisis injection produce valid alternating candles."""
        df_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=40)

        # Whipsaw injection over 8 bars
        df_whip = SyntheticMarketShockInjector.inject_whipsaws(
            df_base, start_idx=10, num_bars=8, oscillation_pct=Decimal("0.05")
        )
        assert len(df_whip) == 40
        for i in range(10, 18):
            o = df_whip.at[i, "open"]
            h = df_whip.at[i, "high"]
            low_val = df_whip.at[i, "low"]
            c = df_whip.at[i, "close"]
            assert h >= max(o, c)
            assert low_val <= min(o, c)

        # Composite crisis injection (flash crash + whipsaw + 50x slippage + 20x spread)
        df_comp = SyntheticMarketShockInjector.inject_composite_crisis(df_base, start_idx=15)
        assert len(df_comp) == 40
        assert df_comp.attrs["slippage_multiplier"] == Decimal("50")
        assert df_comp.attrs["spread_multiplier"] == Decimal("20")

        # Invalid whipsaw parameters
        with pytest.raises(ValueError, match="num_bars must be >= 1"):
            SyntheticMarketShockInjector.inject_whipsaws(
                df_base, start_idx=10, num_bars=0, oscillation_pct=0.05
            )
        with pytest.raises(ValueError, match="exceeds length"):
            SyntheticMarketShockInjector.inject_whipsaws(
                df_base, start_idx=35, num_bars=10, oscillation_pct=0.05
            )

    def test_f5_calculate_adverse_gap_fill_pricing_long_and_short(self) -> None:
        """Verify calculate_adverse_gap_fill pricing under gapped and nominal conditions."""
        slippage_rate = Decimal("0.01")  # 100 bps

        # LONG: Gap down below stop (bar_open < stop_price) -> fills at open minus slippage
        raw_exit, fill_price = calculate_adverse_gap_fill(
            side="LONG",
            bar_open=Decimal("90.00"),
            stop_price=Decimal("95.00"),
            slippage_rate=slippage_rate,
        )
        assert raw_exit == Decimal("90.00")
        assert fill_price == Decimal("90.00") * (Decimal("1.0") - slippage_rate)
        assert fill_price == Decimal("89.10")

        # LONG: Normal fill (bar_open >= stop_price) -> fills at stop minus slippage
        raw_exit_norm, fill_norm = calculate_adverse_gap_fill(
            side="LONG",
            bar_open=Decimal("98.00"),
            stop_price=Decimal("95.00"),
            slippage_rate=slippage_rate,
        )
        assert raw_exit_norm == Decimal("95.00")
        assert fill_norm == Decimal("95.00") * Decimal("0.99")
        assert fill_norm == Decimal("94.05")

        # SHORT: Gap up above stop (bar_open > stop_price) -> fills at open plus slippage
        raw_exit_s, fill_s = calculate_adverse_gap_fill(
            side="SHORT",
            bar_open=Decimal("110.00"),
            stop_price=Decimal("105.00"),
            slippage_rate=slippage_rate,
        )
        assert raw_exit_s == Decimal("110.00")
        assert fill_s == Decimal("110.00") * (Decimal("1.0") + slippage_rate)
        assert fill_s == Decimal("111.10")

        # SHORT: Normal fill (bar_open <= stop_price) -> fills at stop plus slippage
        raw_exit_sn, fill_sn = calculate_adverse_gap_fill(
            side="SHORT",
            bar_open=Decimal("102.00"),
            stop_price=Decimal("105.00"),
            slippage_rate=slippage_rate,
        )
        assert raw_exit_sn == Decimal("105.00")
        assert fill_sn == Decimal("105.00") * Decimal("1.01")
        assert fill_sn == Decimal("106.05")

    def test_f6_hardened_shared_margin_account_initial_state_and_accounting(self) -> None:
        """Verify HardenedSharedMarginAccount initialization, allocation, and cash flows."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        assert account.starting_capital == Decimal("100.00")
        assert account.cash == Decimal("100.00")
        assert account.total_locked_margin() == Decimal("0.00")
        assert account.available_margin(Decimal("100.00")) == Decimal("80.00")
        assert account.margin_utilization(Decimal("100.00")) == Decimal("0.00")
        assert account.unencumbered_reserve_buffer(Decimal("100.00")) == Decimal("1.00")

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
        assert account.margin_utilization(Decimal("100.00")) == Decimal("0.20")
        assert account.unencumbered_reserve_buffer(Decimal("100.00")) == Decimal("0.80")

        # Record close
        gross_pnl = Decimal("2.50")
        exit_fee = Decimal("0.008")
        account.record_close(trade_id="trade-001", gross_pnl=gross_pnl, exit_fee=exit_fee)
        assert account.total_locked_margin() == Decimal("0.00")
        expected_cash = Decimal("99.992") + gross_pnl - exit_fee
        assert account.cash == expected_cash

    def test_f7_dynamic_leverage_deescalation_and_clamping(self) -> None:
        """Verify dynamic leverage scales with conviction and de-escalates to 1.0x under stress."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))

        # Nominal regime: 1.0x at 0.50 conviction, 2.0x at 0.75, 3.0x at 1.00
        assert account.calculate_hardened_leverage(Decimal("0.50")) == Decimal("1.0")
        assert account.calculate_hardened_leverage(Decimal("0.75")) == Decimal("2.0")
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("3.0")

        # Volatility surge: R_vol >= 2.0 clamps leverage to 1.0x
        lev_vol = account.calculate_hardened_leverage(
            confidence=Decimal("1.00"),
            volatility_ratio=Decimal("2.2"),
        )
        assert lev_vol == Decimal("1.0")

        # Slippage surge: R_slip >= 5.0 clamps leverage to 1.0x
        lev_slip = account.calculate_hardened_leverage(
            confidence=Decimal("0.90"),
            slippage_ratio=Decimal("5.5"),
        )
        assert lev_slip == Decimal("1.0")

        # THROTTLED state clamps leverage to 1.0x
        account.current_state = "THROTTLED"
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("1.0")

        # HALTED or EMERGENCY_FLAT clamps leverage to 0.0x (entry inhibition)
        account.current_state = "HALTED"
        assert account.calculate_hardened_leverage(Decimal("0.80")) == Decimal("0.0")
        account.current_state = "EMERGENCY_FLAT"
        assert account.calculate_hardened_leverage(Decimal("0.80")) == Decimal("0.0")

    def test_f8_circuit_breaker_three_stage_monotonic_transitions_and_resume_prohibition(
        self,
    ) -> None:
        """Verify 3-stage circuit breaker transitions monotonically and rejects auto-resume."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

        # 1. Nominal evaluation
        res_norm = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("10.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("2.0"),
            current_equity=Decimal("100.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=now,
        )
        assert res_norm.recommended_state == "NORMAL"
        assert res_norm.inhibit_new_entries is False
        assert res_norm.clamped_max_leverage == Decimal("3.0")
        assert account.current_state == "NORMAL"

        # 2. Transition to THROTTLED on volatility ratio >= 2.0
        res_throt = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("22.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("2.0"),
            current_equity=Decimal("100.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=now + timedelta(minutes=5),
        )
        assert res_throt.recommended_state == "THROTTLED"
        assert res_throt.clamped_max_leverage == Decimal("1.0")
        assert account.current_state == "THROTTLED"

        # 3. Monotonic invariant: stress abating does NOT automatically restore NORMAL
        res_calm = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("10.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("2.0"),
            current_equity=Decimal("100.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=now + timedelta(minutes=10),
        )
        assert res_calm.recommended_state == "THROTTLED"
        assert account.current_state == "THROTTLED"

        # 4. Transition to HALTED on slippage >= 20.0 bps
        res_halt = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("10.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("25.0"),
            current_equity=Decimal("100.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=now + timedelta(minutes=15),
        )
        assert res_halt.recommended_state == "HALTED"
        assert res_halt.inhibit_new_entries is True
        assert account.current_state == "HALTED"

        # 5. Transition to EMERGENCY_FLAT on adverse wick >= 10%
        res_flat = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("10.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("25.0"),
            current_equity=Decimal("100.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=now + timedelta(minutes=20),
            adverse_wick_pct=Decimal("0.12"),
        )
        assert res_flat.recommended_state == "EMERGENCY_FLAT"
        assert account.current_state == "EMERGENCY_FLAT"

        # 6. Automatic resume without complete evidence raises DomainViolation
        with pytest.raises(DomainViolation, match="automatic resume is forbidden"):
            account.request_resume(None)

        with pytest.raises(DomainViolation, match="automatic resume is forbidden"):
            account.request_resume(SimpleNamespace(operator_approved=False))

        # Complete evidence restores NORMAL
        valid_evidence = SimpleNamespace(
            operator_approved=True,
            reconciled=True,
            incident_resolved=True,
            data_fresh=True,
            risk_healthy=True,
        )
        account.request_resume(valid_evidence)
        assert account.current_state == "NORMAL"

    def test_f9_emergency_liquidation_trigger_and_orderly_closeout(self, tmp_path: Path) -> None:
        """Verify emergency liquidation liquidates positions orderly, releasing margin safely."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        equity = Decimal("100.00")

        # Open 2 positions
        alloc1 = account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("50000.00"), equity)
        assert alloc1 is not None
        account.record_open("trade-btc", alloc1[0], alloc1[1], Decimal("0.008"), equity)

        alloc2 = account.allocate_order("ETHUSDT", Decimal("0.50"), Decimal("3000.00"), equity)
        assert alloc2 is not None
        account.record_open("trade-eth", alloc2[0], alloc2[1], Decimal("0.008"), equity)

        assert account.total_locked_margin() == Decimal("40.00")

        now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
        mock_open_entry_btc = SimpleNamespace(
            candidate_id="cand-btc",
            candidate_artifact_hash="hash-btc",
            trade_id="trade-btc",
            symbol="BTCUSDT",
            side="LONG",
            quantity=alloc1[2],
            fill_price=Decimal("50000.00"),
            occurred_at=now - timedelta(minutes=15),
        )
        mock_open_entry_eth = SimpleNamespace(
            candidate_id="cand-eth",
            candidate_artifact_hash="hash-eth",
            trade_id="trade-eth",
            symbol="ETHUSDT",
            side="LONG",
            quantity=alloc2[2],
            fill_price=Decimal("3000.00"),
            occurred_at=now - timedelta(minutes=15),
        )
        active_trades = {
            "BTCUSDT": {
                "trade_id": "trade-btc",
                "open_entry": mock_open_entry_btc,
                "side": "LONG",
                "stop_price": Decimal("48000.00"),
            },
            "ETHUSDT": {
                "trade_id": "trade-eth",
                "open_entry": mock_open_entry_eth,
                "side": "LONG",
                "stop_price": Decimal("2850.00"),
            },
        }

        # Emergency liquidation triggered due to margin buffer depletion
        events = account.emergency_liquidate_positions(
            active_trades=active_trades,
            current_prices={"BTCUSDT": Decimal("47000.00"), "ETHUSDT": Decimal("2800.00")},
            current_opens={"BTCUSDT": Decimal("47500.00"), "ETHUSDT": Decimal("2820.00")},
            slippage_rate=Decimal("0.002"),
            fee_rate=Decimal("0.0004"),
            occurred_at=now,
            reason="margin_buffer_depletion",
        )

        assert len(events) == 2
        assert len(active_trades) == 0  # All closed
        assert account.total_locked_margin() == Decimal("0.00")
        for ev in events:
            assert isinstance(ev, EmergencyLiquidationEvent)
            assert ev.liquidation_reason == "margin_buffer_depletion"
            assert ev.post_close_equity > Decimal("0")  # Deficit strictly forbidden
            assert ev.released_margin == Decimal("20.00")


# ---------------------------------------------------------------------------
# Tier 2: Boundary & Corner Cases
# ---------------------------------------------------------------------------


class TestTier2BoundaryAndEdgeCases:
    """Tier 2: Boundary Value Analysis and Edge Case stress testing."""

    def test_b1_boundary_shock_magnitudes(self) -> None:
        """Verify boundary shock at -10%, extreme -25%, min 5%, max 50%, and invalid bounds."""
        df_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=30)

        # Boundary shock at -10%
        df_10 = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=10, drop_pct=Decimal("0.10")
        )
        assert df_10.at[10, "open"] == df_base.at[10, "open"] * Decimal("0.90")

        # Extreme shock at -25%
        df_25 = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=10, drop_pct=Decimal("0.25")
        )
        assert df_25.at[10, "open"] == df_base.at[10, "open"] * Decimal("0.75")

        # Min boundary 5% and max boundary 50%
        df_min = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=10, drop_pct=Decimal("0.05")
        )
        assert df_min.at[10, "open"] == df_base.at[10, "open"] * Decimal("0.95")

        df_max = SyntheticMarketShockInjector.inject_flash_crash(
            df_base, start_idx=10, drop_pct=Decimal("0.50")
        )
        assert df_max.at[10, "open"] == df_base.at[10, "open"] * Decimal("0.50")

        # Out-of-bounds drop magnitudes
        with pytest.raises(ValueError, match="drop_pct magnitude"):
            SyntheticMarketShockInjector.inject_flash_crash(
                df_base, start_idx=10, drop_pct=Decimal("0.049")
            )
        with pytest.raises(ValueError, match="drop_pct magnitude"):
            SyntheticMarketShockInjector.inject_flash_crash(
                df_base, start_idx=10, drop_pct=Decimal("0.501")
            )

    def test_b2_slippage_surge_boundary_multiplier(self) -> None:
        """Verify 50x slippage surge (100 bps) and 100x multiplier (200 bps boundary limit)."""
        df_base = generate_deterministic_doge_bars(start=DEFAULT_START_TIME, bars_count=20)

        # Baseline 1.0x boundary = 2.0 bps
        df_1x = SyntheticMarketShockInjector.inject_slippage_surge(df_base, multiplier=Decimal("1"))
        assert df_1x.attrs["slippage_bps"] == Decimal("2.0")

        # 50x surge = 100 bps
        df_50x = SyntheticMarketShockInjector.inject_slippage_surge(
            df_base, multiplier=Decimal("50")
        )
        assert df_50x.attrs["slippage_bps"] == Decimal("100.0")

        # 100x surge = 200 bps limit
        df_100x = SyntheticMarketShockInjector.inject_slippage_surge(
            df_base, multiplier=Decimal("100")
        )
        assert df_100x.attrs["slippage_bps"] == Decimal("200.0")

        # Below 1.0 boundary rejected
        with pytest.raises(ValueError, match="multiplier must be >= 1.0"):
            SyntheticMarketShockInjector.inject_slippage_surge(df_base, multiplier=Decimal("0.99"))

    def test_b3_margin_utilization_cap_exact_80_percent_boundary(self) -> None:
        """Verify exactly 80.00% margin utilization cap boundary and rejection of 5th order."""
        account = HardenedSharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            base_allocation_fraction=Decimal("0.20"),
        )
        equity = Decimal("100.00")

        # Allocate 4 positions of 20 USDT each -> 20, 40, 60, 80 USDT locked
        for sym, t_id in [
            ("BTCUSDT", "t1"),
            ("ETHUSDT", "t2"),
            ("SOLUSDT", "t3"),
            ("DOGEUSDT", "t4"),
        ]:
            alloc = account.allocate_order(sym, Decimal("0.50"), Decimal("100.00"), equity)
            assert alloc is not None
            margin, lev, _ = alloc
            account.record_open(t_id, margin, lev, Decimal("0.001"), equity)

        assert account.total_locked_margin() == Decimal("80.00")
        assert account.margin_utilization(equity) == Decimal("0.80")
        assert account.available_margin(equity) == Decimal("0.00")
        assert account.unencumbered_reserve_buffer(equity) == Decimal("0.20")

        # Attempt 5th order allocation: must be rejected as it would exceed 80% cap
        alloc_5th = account.allocate_order("BTCUSDT", Decimal("0.50"), Decimal("100.00"), equity)
        assert alloc_5th is None

    def test_b4_minimum_reserve_buffer_strictly_preserved(self) -> None:
        """Verify unencumbered reserve buffer strictly maintained at >= 20.00%."""
        account = HardenedSharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            min_reserve_buffer=Decimal("0.20"),
            base_allocation_fraction=Decimal("0.20"),
        )
        # Lock 60 USDT (3 positions of 20 USDT)
        account.record_open(
            "t1", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), Decimal("100.00")
        )
        account.record_open(
            "t2", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), Decimal("100.00")
        )
        account.record_open(
            "t3", Decimal("20.00"), Decimal("1.0"), Decimal("0.001"), Decimal("100.00")
        )

        # If equity drops to 70 USDT due to mark-to-market losses:
        # Buffer is (70 - 60) / 70 = 10 / 70 = 14.28% (< 20%)
        equity_depleted = Decimal("70.00")
        assert account.unencumbered_reserve_buffer(equity_depleted) < Decimal("0.20")

        # Any new order must be rejected because buffer_after would be < 20%
        alloc = account.allocate_order(
            "ETHUSDT", Decimal("0.50"), Decimal("100.00"), equity_depleted
        )
        assert alloc is None

    def test_b5_same_candle_stop_loss_and_take_profit_breach(self, tmp_path: Path) -> None:
        """Verify same-candle stop-loss and take-profit breach gives priority to stop-loss."""
        ledger = SqlitePaperLedger(tmp_path / "candle_breach.sqlite3")
        open_entry = PaperLedgerEntry(
            event="open",
            candidate_id=PINNED_TARGETS["BTCUSDT"].candidate_id,
            candidate_artifact_hash=PINNED_TARGETS["BTCUSDT"].artifact_hash,
            trade_id="trade-test-01",
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("1.0"),
            fill_price=Decimal("100.00"),
            occurred_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            entry_fee=Decimal("0.04"),
            slippage_cost=Decimal("0.02"),
        )
        ledger.append(open_entry)

        stop_price = Decimal("95.00")
        target_price = Decimal("110.00")
        now = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)

        # Volatile candle breaches both: open plunged below stop (92.00), high touched 115.00
        # When mark_price is at or below stop, stop_loss_hit is True
        marked_stop = mark_paper_position(
            open_entry,
            mark_price=Decimal("92.00"),
            marked_at=now,
            previous_peak_pnl=Decimal("0.0"),
            stop_loss_price=stop_price,
            take_profit_price=target_price,
        )
        assert marked_stop.stop_loss_hit is True
        assert marked_stop.lifecycle_status == "exit_ready"

        # Adverse gap fill execution pricing: min(bar_open, stop_price) * (1 - slippage)
        bar_open = Decimal("92.00")
        raw_exit, fill_price = calculate_adverse_gap_fill(
            side="LONG",
            bar_open=bar_open,
            stop_price=stop_price,
            slippage_rate=Decimal("0.0002"),
        )
        assert raw_exit == Decimal("92.00")
        assert fill_price < stop_price  # Capital protection penalty applied

    def test_b6_non_negative_equity_guarantee_extreme_gap(self) -> None:
        """Verify equity remains non-negative (Equity > 0) under extreme multi-asset adverse gap."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        equity = Decimal("100.00")

        # Open 4 positions across 4 symbols
        trades = ["t_btc", "t_eth", "t_sol", "t_doge"]
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
        prices = [Decimal("50000.00"), Decimal("3000.00"), Decimal("150.00"), Decimal("0.15")]

        active_trades: dict[str, dict[str, Any]] = {}
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

        for sym, t_id, p in zip(symbols, trades, prices, strict=True):
            alloc = account.allocate_order(sym, Decimal("0.50"), p, equity)
            assert alloc is not None
            margin, lev, qty = alloc
            account.record_open(t_id, margin, lev, Decimal("0.008"), equity)
            mock_entry = SimpleNamespace(
                trade_id=t_id,
                symbol=sym,
                side="LONG",
                quantity=qty,
                fill_price=p,
                occurred_at=now,
            )
            active_trades[sym] = {
                "trade_id": t_id,
                "open_entry": mock_entry,
                "side": "LONG",
                "stop_price": p * Decimal("0.95"),
            }

        # Catastrophic simultaneous -25% gap down on all assets with 50x slippage (100 bps)
        crashed_prices = {sym: p * Decimal("0.75") for sym, p in zip(symbols, prices, strict=True)}
        crashed_opens = {sym: p * Decimal("0.75") for sym, p in zip(symbols, prices, strict=True)}

        events = account.emergency_liquidate_positions(
            active_trades=active_trades,
            current_prices=crashed_prices,
            current_opens=crashed_opens,
            slippage_rate=Decimal("0.01"),  # 100 bps
            fee_rate=Decimal("0.0004"),
            occurred_at=now + timedelta(minutes=5),
            reason="catastrophic_drawdown",
        )

        assert len(events) == 4
        # Assert non-negative equity invariant for all events
        for ev in events:
            assert ev.post_close_equity > Decimal("0")
        assert account.cash > Decimal("0")

    def test_b7_circuit_breaker_config_validation_hierarchy(self) -> None:
        """Verify strict threshold hierarchy validation in CircuitBreakerConfig."""
        # Valid config
        cfg = CircuitBreakerConfig()
        assert cfg.volatility_throttle_ratio < cfg.volatility_halt_ratio

        # Hierarchy violation: volatility throttle >= halt
        with pytest.raises(ValidationError, match="volatility_throttle_ratio must be less"):
            CircuitBreakerConfig(
                volatility_throttle_ratio=Decimal("3.0"),
                volatility_halt_ratio=Decimal("2.5"),
            )

        # Hierarchy violation: slippage throttle >= halt
        with pytest.raises(ValidationError, match="slippage_throttle_bps must be less"):
            CircuitBreakerConfig(
                slippage_throttle_bps=Decimal("25.0"),
                slippage_halt_bps=Decimal("20.0"),
            )

        # Hierarchy violation: drawdown ordering
        with pytest.raises(ValidationError, match="drawdown thresholds must be strictly ordered"):
            CircuitBreakerConfig(
                drawdown_throttle=Decimal("0.09"),
                drawdown_halt=Decimal("0.08"),
            )


# ---------------------------------------------------------------------------
# Tier 3: Pairwise Combinations
# ---------------------------------------------------------------------------


class TestTier3PairwiseCombinations:
    """Tier 3: Pairwise interactions across shocks, margin regimes, and execution penalties."""

    def test_p1_simultaneous_flash_crash_and_50x_slippage_surge(self) -> None:
        """Verify combined flash crash (-20%) and 50x slippage surge (100 bps) adverse execution."""
        # Long entry at 100.00 USDT with protective stop at 96.00 USDT
        entry_price = Decimal("100.00")
        stop_price = Decimal("96.00")
        qty = Decimal("1.0")

        # Sudden flash crash gap down to 80.00 with 50x slippage surge (100 bps = 0.01)
        bar_open = Decimal("80.00")
        slippage_rate = Decimal("0.01")

        raw_exit, fill_price = calculate_adverse_gap_fill(
            side="LONG",
            bar_open=bar_open,
            stop_price=stop_price,
            slippage_rate=slippage_rate,
        )

        assert raw_exit == Decimal("80.00")
        # 80.00 * (1 - 0.01) = 79.20
        assert fill_price == Decimal("79.20")

        # Loss absorbed: (79.20 - 100.00) * 1.0 = -20.80 USDT
        loss = (fill_price - entry_price) * qty
        assert loss == Decimal("-20.80")

    def test_p2_concurrent_positions_entering_volatility_halt_regime(self) -> None:
        """Verify concurrent positions across multiple assets entering volatility halt."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        equity = Decimal("100.00")

        # 3 active positions locked
        account.record_open("t1", Decimal("20.00"), Decimal("1.0"), Decimal("0.008"), equity)
        account.record_open("t2", Decimal("20.00"), Decimal("1.0"), Decimal("0.008"), equity)
        account.record_open("t3", Decimal("20.00"), Decimal("1.0"), Decimal("0.008"), equity)

        # Volatility spike occurs: ATR surges 3.5x baseline -> HALTED state
        eval_result = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("35.0"),
            baseline_atr=Decimal("10.0"),
            current_slippage_bps=Decimal("2.0"),
            current_equity=Decimal("98.00"),
            peak_equity=Decimal("100.00"),
            bar_ts=datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
        )
        assert eval_result.recommended_state == "HALTED"
        assert eval_result.inhibit_new_entries is True
        assert account.current_state == "HALTED"

        # Candidate 4 (DOGEUSDT) generates entry signal with 1.0 conviction
        alloc = account.allocate_order("DOGEUSDT", Decimal("1.00"), Decimal("0.15"), equity)
        # Entry must be rejected because account is HALTED
        assert alloc is None

        # Existing positions can still close safely
        account.record_close("t1", gross_pnl=Decimal("1.00"), exit_fee=Decimal("0.008"))
        assert account.total_locked_margin() == Decimal("40.00")

    def test_p3_emergency_liquidation_during_active_spread_blowout(self) -> None:
        """Verify emergency liquidation during active 20x spread blowout (40 bps friction)."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        equity = Decimal("100.00")

        alloc = account.allocate_order("SOLUSDT", Decimal("0.50"), Decimal("150.00"), equity)
        assert alloc is not None
        account.record_open("trade-sol", alloc[0], alloc[1], Decimal("0.008"), equity)

        now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
        mock_entry = SimpleNamespace(
            trade_id="trade-sol",
            symbol="SOLUSDT",
            side="LONG",
            quantity=alloc[2],
            fill_price=Decimal("150.00"),
            occurred_at=now - timedelta(minutes=10),
        )
        active_trades = {
            "SOLUSDT": {
                "trade_id": "trade-sol",
                "open_entry": mock_entry,
                "side": "LONG",
                "stop_price": Decimal("142.00"),
            }
        }

        # 20x spread blowout (40 bps execution friction = 0.004)
        spread_blowout_rate = Decimal("0.004")
        events = account.emergency_liquidate_positions(
            active_trades=active_trades,
            current_prices={"SOLUSDT": Decimal("140.00")},
            current_opens={"SOLUSDT": Decimal("141.00")},
            slippage_rate=spread_blowout_rate,
            fee_rate=Decimal("0.0004"),
            occurred_at=now,
            reason="circuit_breaker_emergency_flat",
        )

        assert len(events) == 1
        ev = events[0]
        assert ev.executed_fill_price == Decimal("141.00") * (Decimal("1.0") - spread_blowout_rate)
        assert ev.post_close_equity > Decimal("0")
        assert account.total_locked_margin() == Decimal("0.00")

    def test_p4_dynamic_leverage_and_allocation_halving_in_throttled_state(self) -> None:
        """Verify in THROTTLED state base margin is halved to 10% and leverage clamped to 1.0x."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        account.current_state = "THROTTLED"
        equity = Decimal("100.00")

        # High-conviction signal (0.90 conviction normally yields 2.6x leverage and 20% margin)
        alloc = account.allocate_order("BTCUSDT", Decimal("0.90"), Decimal("50000.00"), equity)
        assert alloc is not None
        base_margin, leverage, quantity = alloc

        # In THROTTLED: margin is halved from 20% to 10% (10 USDT), leverage clamped to 1.0x
        assert base_margin == Decimal("10.00")
        assert leverage == Decimal("1.0")
        notional = base_margin * leverage
        assert notional == Decimal("10.00")
        assert quantity == Decimal("0.000200")


# ---------------------------------------------------------------------------
# Tier 4: Real-World Scenarios
# ---------------------------------------------------------------------------


class TestTier4RealWorldScenarios:
    """Tier 4: Comprehensive end-to-end execution, stress testing, and artifact verification."""

    def test_s1_full_simulation_track_0_baseline_e2e(self, tmp_path: Path) -> None:
        """Scenario 1: End-to-end execution of baseline track across 144 bars in isolated store."""
        output_dir = tmp_path / "track_0_baseline_test"
        candidates = load_phase_255_candidates()
        raw_market_frames = {
            sym: load_symbol_market_frame(sym, start=DEFAULT_START_TIME, total_bars=144)
            for sym in candidates
        }

        res = run_single_stress_track(
            track_spec=TRACK_DEFINITIONS[0],
            output_dir=output_dir,
            candidates=candidates,
            raw_market_frames=raw_market_frames,
            total_bars=144,
            starting_equity=Decimal("100.00"),
        )

        assert res.track_id == 0
        assert res.track_name == "baseline"
        assert res.positions_reconciled is True
        assert res.accounting_reconciled is True
        assert res.scenario_result.capital_survived is True
        assert res.scenario_result.account_liquidated is False
        assert res.scenario_result.deficit_balance is False
        assert res.final_cash > Decimal("0")
        assert (output_dir / "paper-ledger.sqlite3").is_file()
        assert (output_dir / "paper-lifecycle.sqlite3").is_file()
        assert (output_dir / "paper-observations.sqlite3").is_file()

    def test_s2_full_simulation_track_1_flash_crash_e2e(self, tmp_path: Path) -> None:
        """Scenario 2: End-to-end execution of flash crash track with shock at bar 30."""
        output_dir = tmp_path / "track_1_flash_crash_test"
        candidates = load_phase_255_candidates()
        raw_market_frames = {
            sym: load_symbol_market_frame(sym, start=DEFAULT_START_TIME, total_bars=144)
            for sym in candidates
        }

        track_spec = dict(TRACK_DEFINITIONS[1])
        track_spec["shock_bar_index"] = 30

        res = run_single_stress_track(
            track_spec=track_spec,
            output_dir=output_dir,
            candidates=candidates,
            raw_market_frames=raw_market_frames,
            total_bars=144,
            starting_equity=Decimal("100.00"),
        )

        assert res.track_id == 1
        assert res.positions_reconciled is True
        assert res.accounting_reconciled is True
        assert res.scenario_result.capital_survived is True
        assert res.scenario_result.account_liquidated is False
        assert res.scenario_result.deficit_balance is False
        assert res.final_cash > Decimal("0")

    def test_s3_full_simulation_track_5_composite_crisis_e2e(self, tmp_path: Path) -> None:
        """Scenario 3: End-to-end execution of composite crisis track with shock at bar 30."""
        output_dir = tmp_path / "track_5_composite_test"
        candidates = load_phase_255_candidates()
        raw_market_frames = {
            sym: load_symbol_market_frame(sym, start=DEFAULT_START_TIME, total_bars=144)
            for sym in candidates
        }

        track_spec = dict(TRACK_DEFINITIONS[5])
        track_spec["shock_bar_index"] = 30

        res = run_single_stress_track(
            track_spec=track_spec,
            output_dir=output_dir,
            candidates=candidates,
            raw_market_frames=raw_market_frames,
            total_bars=144,
            starting_equity=Decimal("100.00"),
        )

        assert res.track_id == 5
        assert res.positions_reconciled is True
        assert res.accounting_reconciled is True
        assert res.scenario_result.capital_survived is True
        assert res.scenario_result.account_liquidated is False
        assert res.scenario_result.deficit_balance is False
        assert res.final_cash > Decimal("0")
        assert res.scenario_result.max_observed_margin_utilization <= Decimal("0.80")
        assert res.scenario_result.min_observed_equity_buffer >= Decimal("0.20")

    def test_s4_persisted_artifact_stress_test_summary_verification(self) -> None:
        """Scenario 4: Authoritative verification of persisted stress-test-summary.json."""
        summary_path = Path("artifacts/research/phase255/stress-test-summary.json")
        assert summary_path.is_file(), f"Missing {summary_path}"

        summary_text = summary_path.read_text(encoding="utf-8")
        _assert_zero_secrets(summary_text, "stress-test-summary.json")

        data = json.loads(summary_text)
        assert data["phase"] == "phase_255"
        assert data["bundle_hash"] == PINNED_BUNDLE_HASH
        assert data["dataset_registry_hash"] == PINNED_REGISTRY_HASH
        assert data["total_tracks"] == 6
        assert data["all_tracks_survived"] is True
        assert data["zero_deficit_balance"] is True
        assert data["zero_account_liquidation"] is True
        assert data["zero_balance_drift_verified"] is True
        assert data["max_utilization_cap_satisfied"] is True
        assert data["min_reserve_buffer_satisfied"] is True

        expected_tracks = [
            "baseline",
            "flash_crash",
            "slippage_surge",
            "spread_blowout",
            "volatility_whipsaw",
            "composite_crisis",
        ]
        assert data["scenarios_evaluated"] == expected_tracks

        tracks = data["tracks"]
        for t_name in expected_tracks:
            assert t_name in tracks
            t_data = tracks[t_name]
            end_eq = Decimal(t_data["ending_equity"])
            min_eq = Decimal(t_data["min_observed_equity"])
            max_util = Decimal(t_data["max_observed_margin_utilization"])
            min_buf = Decimal(t_data["min_observed_equity_buffer"])

            # Core survival and margin assertions
            assert end_eq > Decimal("0"), f"Track {t_name} ended with non-positive equity"
            assert min_eq > Decimal("0"), f"Track {t_name} dipped to non-positive equity"
            assert max_util <= Decimal("0.80"), f"Track {t_name} breached 80% utilization"
            assert min_buf >= Decimal("0.20"), f"Track {t_name} buffer fell below 20%"
            assert t_data["capital_survived"] is True
            assert t_data["account_liquidated"] is False
            assert t_data["deficit_balance"] is False
            assert t_data["zero_balance_drift"] is True

    def test_s5_persisted_sqlite_database_stores_integrity(self) -> None:
        """Scenario 5: Verify schema and non-empty records in generated Phase 255 SQLite stores."""
        base_dir = Path("artifacts/research/phase255")
        for db_name, table_name in [
            ("paper-ledger.sqlite3", "paper_ledger_events"),
            ("paper-lifecycle.sqlite3", "paper_lifecycle_marks"),
            ("paper-observations.sqlite3", "paper_observations"),
        ]:
            db_path = base_dir / db_name
            assert db_path.is_file(), f"Missing SQLite database: {db_path}"
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                assert cursor.fetchone() is not None, f"Table {table_name} missing from {db_name}"
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                assert count > 0, f"Table {table_name} is unexpectedly empty"

        # Verify track-specific isolated stores exist
        tracks_dir = base_dir / "tracks"
        assert tracks_dir.is_dir()
        track_dirs = list(tracks_dir.glob("track_*"))
        assert len(track_dirs) == 6
        for t_dir in track_dirs:
            assert (t_dir / "paper-ledger.sqlite3").is_file()
            assert (t_dir / "paper-lifecycle.sqlite3").is_file()
            assert (t_dir / "paper-observations.sqlite3").is_file()

    def test_s6_offline_safety_invariants_and_zero_secret_leakage(self) -> None:
        """Scenario 6: Verify offline safety invariants and zero secrets across artifacts."""
        # Clean safety check execution
        assert_offline_safety_invariants()

        summary_path = Path("artifacts/research/phase255/stress-test-summary.json")
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        inv = data["offline_safety_invariants"]

        assert inv["orders"] == 0
        assert inv["exchange_access"] is False
        assert inv["execution_authority"] is False
        assert inv["promotion_state"] == "unpromoted"
        assert inv["paper_activation"] is False
        assert inv["data_source"] == "cached_only"
        assert inv["zero_secret_leakage"] is True

        # Assert secret detector catches mock keys
        with pytest.raises(DomainViolation, match="Security secret pattern detected"):
            _assert_zero_secrets("AIzaSyD123456789012345678901234567890", "test_api_key")

    def test_s7_cli_runner_execution_and_track_filtering(self, tmp_path: Path) -> None:
        """Scenario 7: Standalone CLI invocation of main() with track filtering producing code 0."""
        cli_out = tmp_path / "cli_run"
        exit_code = main(
            [
                "--output-dir",
                str(cli_out),
                "--bars",
                "36",
                "--track",
                "baseline",
            ]
        )
        assert exit_code == 0
        assert (cli_out / "stress-test-summary.json").is_file()
        assert (cli_out / "paper-ledger.sqlite3").is_file()
        assert (cli_out / "paper-lifecycle.sqlite3").is_file()
        assert (cli_out / "paper-observations.sqlite3").is_file()

    def test_s8_exact_decimal_accounting_and_zero_drift_across_all_tracks(self) -> None:
        """Scenario 8: Verify exact Decimal accounting and zero balance drift for all 6 tracks."""
        summary_path = Path("artifacts/research/phase255/stress-test-summary.json")
        data = json.loads(summary_path.read_text(encoding="utf-8"))

        for _t_name, t_data in data["tracks"].items():
            start_eq = Decimal(t_data["starting_equity"])
            end_eq = Decimal(t_data["ending_equity"])
            min_eq = Decimal(t_data["min_observed_equity"])
            max_util = Decimal(t_data["max_observed_margin_utilization"])
            min_buf = Decimal(t_data["min_observed_equity_buffer"])

            assert start_eq == Decimal("100.00")
            assert end_eq > Decimal("0.0")
            assert min_eq > Decimal("0.0")
            assert max_util <= Decimal("0.80")
            assert min_buf >= Decimal("0.20")
            assert t_data["zero_balance_drift"] is True
            assert t_data["deficit_balance"] is False
            assert t_data["account_liquidated"] is False
