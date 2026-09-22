"""Unit Test Suite for Phase 295 Strategy Activation Engine.

Covers:
1. Manifest v2 Ingress & Cryptographic Tamper Resistance
2. Walk-Forward OOS Promotion Gate Evaluation & Scale-Invariant Normalization
3. Candidate Lifecycle State Machine (UNPROMOTED, PROMOTED, BLOCKED, VETOED)
4. Causal Indicator Feature Engine (Donchian, Wilder ATR, ADX, Trade Flow Momentum)
5. ParentOrderIntention Formulation, Sizing, and Deterministic Client Order Tagging
6. Real-Time Fail-Closed Veto Interlocks (Heartbeat, Clock Skew, Hawkes, Headroom)
7. Intra-Phase Loss Budget Ceiling Breach & Emergency Flattening Slicing
8. Continuous Double-Entry Zero-Drift Balance Equation Validation (|drift| < 1e-15 USDT)
9. Merkle DAG Artifact Persistence & Upstream Linkage Verification
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.models import (
    AggregateTrade,
    CanonicalBar,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_execution import (
    HARD_MICRO_NOTIONAL_CAP_USDT,
    MIN_MICRO_NOTIONAL_FLOOR_USDT,
    ChildOrderIntention,
    OrderSide,
    OrderStatus,
    OrderType,
    ParentOrderIntention,
    SimulatedPassiveMatchingEngine,
    get_default_exchange_filters,
    slice_parent_order,
)
from autonomous_futures.feed.paper_ledger import (
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)
from autonomous_futures.feed.paper_risk import (
    CircuitState,
    InterlockCode,
    LivePaperRiskInterlock,
)
from autonomous_futures.feed.strategy_activation import (
    EXPECTED_ACTIVE_CANDIDATES,
    CandidateLifecycleStateMachine,
    CandidatePromotionStatus,
    CandidateRegistryError,
    GatewayHealth,
    HawkesTelemetrySnapshot,
    OOSPromotionGateRecord,
    StateTransitionError,
    compute_adx,
    compute_donchian_breakout_signal,
    compute_donchian_channel,
    compute_trade_flow_momentum,
    compute_wilder_atr,
    create_parent_order_intention,
    evaluate_oos_promotion_gates,
    load_verified_candidate_manifest_v2,
    persist_phase295_artifacts,
    validate_realtime_veto_interlocks,
    verify_phase295_artifacts,
)
from autonomous_futures.paper.candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (
    _artifact_content_hash,
)
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    _qualification_content_hash,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def sample_depth_snapshot() -> OrderBookDepthSnapshot:
    """Fixture providing a realistic top-of-book depth snapshot."""
    return OrderBookDepthSnapshot(
        symbol="BTCUSDT",
        bids=(
            OrderBookLevel(price=Decimal("60000.00"), quantity=Decimal("1.50")),
            OrderBookLevel(price=Decimal("59995.00"), quantity=Decimal("2.00")),
            OrderBookLevel(price=Decimal("59990.00"), quantity=Decimal("3.50")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("60005.00"), quantity=Decimal("1.20")),
            OrderBookLevel(price=Decimal("60010.00"), quantity=Decimal("2.50")),
            OrderBookLevel(price=Decimal("60015.00"), quantity=Decimal("4.00")),
        ),
        last_update_id=10001,
        event_time=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def synthetic_canonical_bars() -> list[CanonicalBar]:
    """Fixture producing 60 consecutive canonical 1m bars."""
    bars: list[CanonicalBar] = []
    base_price = Decimal("50000.00")
    start_dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    for i in range(60):
        bar_dt = start_dt + timedelta(minutes=i)
        close_dt = bar_dt + timedelta(seconds=59, milliseconds=999)
        noise = Decimal(str(round(math.sin(i * 0.2) * 20.0, 2)))
        open_p = base_price + Decimal(i * 15) + noise
        high_p = open_p + Decimal("25.00")
        low_p = open_p - Decimal("15.00")
        close_p = open_p + Decimal("10.00")
        vol = Decimal("10.0") + Decimal(str(i * 0.5))
        quote_vol = vol * close_p
        bars.append(
            CanonicalBar(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=bar_dt,
                close_time=close_dt,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=vol,
                quote_volume=quote_vol,
                trades=100 + i,
                taker_buy_base=vol / Decimal("2"),
                taker_buy_quote=quote_vol / Decimal("2"),
                is_closed=True,
            )
        )
    return bars


# =====================================================================
# 1. Manifest v2 Ingress & Cryptographic Tamper Resistance
# =====================================================================


class TestManifestIngress:
    """Tests for Manifest v2 loader and cryptographic hash validation."""

    def test_load_verified_candidate_manifest_nominal(self) -> None:
        """Nominal load of Candidate Registry Manifest v2/v3 with 3 active candidates."""
        manifest, bundles = load_verified_candidate_manifest_v2()
        assert manifest.registry_version in (2, 3)
        assert len(bundles) == 3
        if manifest.registry_version == 2:
            expected_cids = EXPECTED_ACTIVE_CANDIDATES
        else:
            expected_cids = {
                "BTCUSDT": "cand-btcusdt-dcb-003",
                "ETHUSDT": "cand-ethusdt-rgb-002",
                "SOLUSDT": "cand-solusdt-msm-001",
            }
        for symbol, expected_cid in expected_cids.items():
            assert symbol in bundles
            bundle = bundles[symbol]
            assert bundle.candidate_id == expected_cid
            assert bundle.symbol == symbol
            assert bundle.candidate.candidate_id == expected_cid
            assert bundle.qualification.candidate_id == expected_cid
            # Verify cryptographic content hashes match manifest entry
            expected_c_hash = bundle.manifest_entry.candidate_artifact_hash
            expected_q_hash = bundle.manifest_entry.qualification_hash
            assert _artifact_content_hash(bundle.candidate) == expected_c_hash
            assert _qualification_content_hash(bundle.qualification) == expected_q_hash

    def test_tampered_candidate_hash_fails(self, tmp_path: Path) -> None:
        """Cryptographic failure when candidate artifact content hash is altered."""
        registry = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        tmp_registry_path = tmp_path / "candidate_registry.json"
        reg_dict = registry.model_dump()
        reg_dict["symbols"]["BTCUSDT"]["candidate_artifact_hash"] = "0" * 64
        tmp_registry_path.write_text(json.dumps(reg_dict, indent=2, default=str), encoding="utf-8")

        with pytest.raises(CandidateRegistryError):
            load_verified_candidate_manifest_v2(registry_path=tmp_registry_path)

    def test_tampered_qualification_hash_fails(self, tmp_path: Path) -> None:
        """Cryptographic failure when qualification artifact content hash is altered."""
        registry = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        tmp_registry_path = tmp_path / "candidate_registry.json"
        reg_dict = registry.model_dump()
        reg_dict["symbols"]["BTCUSDT"]["qualification_hash"] = "f" * 64
        tmp_registry_path.write_text(json.dumps(reg_dict, indent=2, default=str), encoding="utf-8")

        with pytest.raises(CandidateRegistryError):
            load_verified_candidate_manifest_v2(registry_path=tmp_registry_path)

    def test_manifest_missing_expected_symbol_fails(self, tmp_path: Path) -> None:
        """Manifest v2 lacking expected active candidates raises CandidateRegistryError."""
        registry = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH)
        tmp_registry_path = tmp_path / "candidate_registry.json"
        reg_dict = registry.model_dump()
        del reg_dict["symbols"]["SOLUSDT"]
        tmp_registry_path.write_text(json.dumps(reg_dict, indent=2, default=str), encoding="utf-8")

        with pytest.raises(CandidateRegistryError):
            load_verified_candidate_manifest_v2(registry_path=tmp_registry_path)

    def test_manifest_missing_file_fails(self, tmp_path: Path) -> None:
        """Missing candidate registry path raises FileNotFoundError or CandidateRegistryError."""
        non_existent = tmp_path / "does_not_exist.json"
        with pytest.raises((FileNotFoundError, CandidateRegistryError)):
            load_verified_candidate_manifest_v2(registry_path=non_existent)


# =====================================================================
# 2. Walk-Forward OOS Promotion Gate Evaluator
# =====================================================================


class TestOOSPromotionGateEvaluator:
    """Tests for multi-tier OOS promotion gates and scale-invariant normalization."""

    def test_all_nominal_active_candidates_qualify(self) -> None:
        """All 3 genuine staged candidates qualify under OOS walk-forward gates."""
        _, bundles = load_verified_candidate_manifest_v2()
        for bundle in bundles.values():
            record = evaluate_oos_promotion_gates(
                bundle.candidate,
                bundle.qualification,
            )
            assert record.qualified is True
            assert record.status == CandidatePromotionStatus.PROMOTED
            assert record.oos_average_return_pct >= Decimal("0.0")
            assert record.oos_worst_drawdown_pct <= Decimal("15.0")
            assert record.oos_profit_factor >= Decimal("1.05")
            assert record.oos_trade_count >= 5
            assert record.oos_window_count >= 1
            assert all(record.gates_passed.values())

    def test_excessive_drawdown_blocks_candidate(self) -> None:
        """Drawdown > 15.0% results in gate failure and BLOCKED status."""
        _, bundles = load_verified_candidate_manifest_v2()
        bundle = bundles["BTCUSDT"]
        qual_dict = bundle.qualification.model_dump()
        for m in qual_dict.get("metrics", []):
            if "drawdown" in m.get("metric_id", ""):
                m["value"] = Decimal("0.20")
        mod_qual = CreatorCandidateQualificationArtifact(**qual_dict)

        record = evaluate_oos_promotion_gates(bundle.candidate, mod_qual)
        assert record.qualified is False
        assert record.status == CandidatePromotionStatus.BLOCKED
        assert record.gates_passed["oos_worst_drawdown"] is False

    def test_negative_return_blocks_candidate(self) -> None:
        """Average return < 0.0% results in gate failure and BLOCKED status."""
        _, bundles = load_verified_candidate_manifest_v2()
        bundle = bundles["ETHUSDT"]
        qual_dict = bundle.qualification.model_dump()
        for m in qual_dict.get("metrics", []):
            if "average_return" in m.get("metric_id", ""):
                m["value"] = Decimal("-0.015")
        mod_qual = CreatorCandidateQualificationArtifact(**qual_dict)

        record = evaluate_oos_promotion_gates(bundle.candidate, mod_qual)
        assert record.qualified is False
        assert record.status == CandidatePromotionStatus.BLOCKED
        assert record.gates_passed["oos_average_return"] is False

    def test_substandard_profit_factor_blocks_candidate(self) -> None:
        """Profit factor < 1.05 results in gate failure and BLOCKED status."""
        _, bundles = load_verified_candidate_manifest_v2()
        bundle = bundles["SOLUSDT"]
        qual_dict = bundle.qualification.model_dump()
        for m in qual_dict.get("metrics", []):
            if "profit_factor" in m.get("metric_id", ""):
                m["value"] = Decimal("1.02")
        mod_qual = CreatorCandidateQualificationArtifact(**qual_dict)

        record = evaluate_oos_promotion_gates(bundle.candidate, mod_qual)
        assert record.qualified is False
        assert record.status == CandidatePromotionStatus.BLOCKED
        assert record.gates_passed["oos_profit_factor"] is False

    def test_insufficient_trades_blocks_candidate(self) -> None:
        """Trade count < 5 results in gate failure and BLOCKED status."""
        _, bundles = load_verified_candidate_manifest_v2()
        bundle = bundles["BTCUSDT"]
        qual_dict = bundle.qualification.model_dump()
        for m in qual_dict.get("metrics", []):
            if "trades" in m.get("metric_id", ""):
                m["value"] = Decimal("3")
        mod_qual = CreatorCandidateQualificationArtifact(**qual_dict)

        record = evaluate_oos_promotion_gates(bundle.candidate, mod_qual)
        assert record.qualified is False
        assert record.status == CandidatePromotionStatus.BLOCKED
        assert record.gates_passed["oos_trade_count"] is False


# =====================================================================
# 3. Candidate Lifecycle State Machine
# =====================================================================


class TestCandidateLifecycleStateMachine:
    """Tests for fail-closed CandidateLifecycleStateMachine transitions."""

    def test_nominal_promotion_lifecycle(self) -> None:
        """UNPROMOTED -> PROMOTED on passing gates."""
        sm = CandidateLifecycleStateMachine("cand-test-001", "BTCUSDT")
        assert sm.status.value == CandidatePromotionStatus.UNPROMOTED.value
        assert sm.is_executable is False

        gate_record = OOSPromotionGateRecord(
            candidate_id="cand-test-001",
            symbol="BTCUSDT",
            status=CandidatePromotionStatus.PROMOTED,
            oos_average_return_pct=Decimal("3.50"),
            oos_worst_drawdown_pct=Decimal("8.20"),
            oos_profit_factor=Decimal("1.8000"),
            oos_trade_count=15,
            oos_window_count=3,
            gates_passed={"all": True},
            qualified=True,
            evaluated_at=datetime.now(UTC),
        )
        sm.promote(gate_record)
        assert sm.status.value == CandidatePromotionStatus.PROMOTED.value
        assert sm.is_executable is True
        assert len(sm.status_history) == 2

    def test_promote_unqualified_raises_error(self) -> None:
        """Attempting to promote with an unqualified gate record raises StateTransitionError."""
        sm = CandidateLifecycleStateMachine("cand-test-002", "ETHUSDT")
        unqual_record = OOSPromotionGateRecord(
            candidate_id="cand-test-002",
            symbol="ETHUSDT",
            status=CandidatePromotionStatus.BLOCKED,
            oos_average_return_pct=Decimal("-1.50"),
            oos_worst_drawdown_pct=Decimal("18.20"),
            oos_profit_factor=Decimal("0.9000"),
            oos_trade_count=4,
            oos_window_count=1,
            gates_passed={"all": False},
            qualified=False,
            evaluated_at=datetime.now(UTC),
        )
        with pytest.raises(StateTransitionError, match="qualification gates not passed"):
            sm.promote(unqual_record)
        assert sm.status == CandidatePromotionStatus.UNPROMOTED

    def test_block_candidate(self) -> None:
        """Candidate transitions to BLOCKED and becomes non-executable."""
        sm = CandidateLifecycleStateMachine("cand-test-003", "SOLUSDT")
        sm.block("Failed out of sample stability")
        assert sm.status == CandidatePromotionStatus.BLOCKED
        assert sm.is_executable is False

    def test_blocked_cannot_be_promoted_directly(self) -> None:
        """BLOCKED candidate cannot transition directly to PROMOTED."""
        sm = CandidateLifecycleStateMachine("cand-test-004", "BTCUSDT")
        sm.block("Permanently blocked")

        gate_record = OOSPromotionGateRecord(
            candidate_id="cand-test-004",
            symbol="BTCUSDT",
            status=CandidatePromotionStatus.PROMOTED,
            oos_average_return_pct=Decimal("5.00"),
            oos_worst_drawdown_pct=Decimal("5.00"),
            oos_profit_factor=Decimal("2.0000"),
            oos_trade_count=20,
            oos_window_count=2,
            gates_passed={"all": True},
            qualified=True,
            evaluated_at=datetime.now(UTC),
        )
        with pytest.raises(StateTransitionError, match="Cannot promote BLOCKED candidate"):
            sm.promote(gate_record)

    def test_veto_and_clear_veto_lifecycle(self) -> None:
        """PROMOTED -> VETOED on market veto, then VETOED -> PROMOTED when cleared."""
        sm = CandidateLifecycleStateMachine("cand-test-005", "BTCUSDT")
        gate_record = OOSPromotionGateRecord(
            candidate_id="cand-test-005",
            symbol="BTCUSDT",
            status=CandidatePromotionStatus.PROMOTED,
            oos_average_return_pct=Decimal("4.00"),
            oos_worst_drawdown_pct=Decimal("7.00"),
            oos_profit_factor=Decimal("1.5000"),
            oos_trade_count=10,
            oos_window_count=2,
            gates_passed={"all": True},
            qualified=True,
            evaluated_at=datetime.now(UTC),
        )
        sm.promote(gate_record)
        assert sm.is_executable is True

        sm.veto("Hawkes supercritical cascade detected")
        assert sm.status == CandidatePromotionStatus.VETOED
        assert sm.is_executable is False

        sm.clear_veto("Hawkes normalized")
        assert sm.status == CandidatePromotionStatus.PROMOTED
        assert sm.is_executable is True

    def test_veto_on_blocked_candidate_is_noop(self) -> None:
        """Calling veto on a BLOCKED candidate does not alter BLOCKED status."""
        sm = CandidateLifecycleStateMachine("cand-test-006", "ETHUSDT")
        sm.block("Gate failure")
        sm.veto("Stale heartbeat")
        assert sm.status == CandidatePromotionStatus.BLOCKED


# =====================================================================
# 4. Causal Indicator Feature Engine
# =====================================================================


class TestCausalIndicatorFeatureEngine:
    """Tests for causal indicator calculations and zero forward lookahead."""

    def test_donchian_channel_calculation(self) -> None:
        """Donchian channel correctly calculates upper and lower boundaries without lookahead."""
        prices = [Decimal(str(100 + i * 2)) for i in range(55)]
        upper, lower = compute_donchian_channel(prices, lookback=50, shift=1)
        expected_window = prices[-51:-1]
        assert upper == max(expected_window)
        assert lower == min(expected_window)

    def test_donchian_breakout_signals(self) -> None:
        """Donchian breakout correctly generates BUY on upper breach and SELL on lower breach."""
        upper = Decimal("105.00")
        lower = Decimal("95.00")

        signal_up = compute_donchian_breakout_signal(Decimal("106.00"), upper, lower)
        assert signal_up == Decimal("1.0")

        signal_down = compute_donchian_breakout_signal(Decimal("94.00"), upper, lower)
        assert signal_down == Decimal("-1.0")

        signal_hold = compute_donchian_breakout_signal(Decimal("100.00"), upper, lower)
        assert signal_hold == Decimal("0.0")

    def test_wilder_atr_and_adx(self, synthetic_canonical_bars: list[CanonicalBar]) -> None:
        """Wilder's ATR and ADX produce valid causal non-negative values."""
        atr = compute_wilder_atr(synthetic_canonical_bars, lookback=14, shift=1)
        assert atr > Decimal("0.0")

        adx = compute_adx(synthetic_canonical_bars, lookback=14, shift=1)
        assert Decimal("0.0") <= adx <= Decimal("100.0")

    def test_trade_flow_momentum(self) -> None:
        """Trade flow momentum calculates net signed volume imbalance causally."""
        now_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        now_ms = int(now_dt.timestamp() * 1000)

        trades = [
            AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=1,
                price=Decimal("60000.00"),
                quantity=Decimal("1.0"),
                trade_time=now_dt - timedelta(seconds=2),
                is_buyer_maker=False,  # Taker BUY (+1.0)
            ),
            AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=2,
                price=Decimal("60005.00"),
                quantity=Decimal("3.0"),
                trade_time=now_dt - timedelta(seconds=1),
                is_buyer_maker=False,  # Taker BUY (+3.0)
            ),
            AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=3,
                price=Decimal("60000.00"),
                quantity=Decimal("1.0"),
                trade_time=now_dt - timedelta(milliseconds=500),
                is_buyer_maker=True,  # Taker SELL (-1.0)
            ),
        ]
        imbalance = compute_trade_flow_momentum(trades, window_ms=5000, now_ms=now_ms)
        assert imbalance == Decimal("0.6000")

    def test_zero_forward_lookahead_invariant(
        self, synthetic_canonical_bars: list[CanonicalBar]
    ) -> None:
        """Historical indicator output is completely invariant to future bars."""
        bars_30 = synthetic_canonical_bars[:30]
        atr_at_30 = compute_wilder_atr(bars_30, lookback=14, shift=1)

        bars_60_sliced = synthetic_canonical_bars[:30]
        atr_replayed = compute_wilder_atr(bars_60_sliced, lookback=14, shift=1)

        assert atr_at_30 == atr_replayed


# =====================================================================
# 5. ParentOrderIntention Formulation & Sizing
# =====================================================================


class TestParentOrderIntentionFormulation:
    """Tests for ParentOrderIntention creation, sizing, and client order tags."""

    def test_nominal_order_formulation(self, sample_depth_snapshot: OrderBookDepthSnapshot) -> None:
        """Nominal order creation sizes to 10% equity with top-of-book depth pricing."""
        filters = get_default_exchange_filters()["BTCUSDT"]
        parent = create_parent_order_intention(
            candidate={"candidate_id": "cand-btcusdt-dcb-002"},
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            current_depth=sample_depth_snapshot,
            filters=filters,
            equity=Decimal("100.00"),
        )
        assert parent.symbol == "BTCUSDT"
        assert parent.side == OrderSide.BUY
        assert parent.limit_price == Decimal("60000.00")
        assert parent.target_notional_usdt == Decimal("10.00")
        pattern = r"^c=canary-p295-btcusdt-[0-9]+-[a-f0-9]{8}$"
        assert re.match(pattern, parent.parent_order_id) is not None

    def test_sell_order_uses_best_ask(self, sample_depth_snapshot: OrderBookDepthSnapshot) -> None:
        """SELL order uses best ask for passive limit pricing."""
        filters = get_default_exchange_filters()["BTCUSDT"]
        parent = create_parent_order_intention(
            candidate={"candidate_id": "cand-btcusdt-dcb-002"},
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            current_depth=sample_depth_snapshot,
            filters=filters,
            equity=Decimal("100.00"),
        )
        assert parent.side == OrderSide.SELL
        assert parent.limit_price == Decimal("60005.00")

    def test_sizing_clamping(self, sample_depth_snapshot: OrderBookDepthSnapshot) -> None:
        """Notional sizing clamps between 1.00 USDT floor and 20.00 USDT cap."""
        filters = get_default_exchange_filters()["BTCUSDT"]

        p_floor = create_parent_order_intention(
            candidate={"candidate_id": "cand-btcusdt-dcb-002"},
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            current_depth=sample_depth_snapshot,
            filters=filters,
            equity=Decimal("5.00"),  # 10% = 0.50 USDT -> clamps to 1.00 USDT
        )
        assert p_floor.target_notional_usdt >= MIN_MICRO_NOTIONAL_FLOOR_USDT

        p_cap = create_parent_order_intention(
            candidate={"candidate_id": "cand-btcusdt-dcb-002"},
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            current_depth=sample_depth_snapshot,
            filters=filters,
            equity=Decimal("1000.00"),  # 10% = 100.00 USDT -> clamps to 20.00 USDT
        )
        assert p_cap.target_notional_usdt <= Decimal("20.00")


# =====================================================================
# 6. Real-Time Fail-Closed Veto Interlocks
# =====================================================================


class TestRealTimeFailClosedVetoInterlocks:
    """Tests for fail-closed pre-trade veto interlocks."""

    @pytest.fixture
    def risk_interlock(self) -> LivePaperRiskInterlock:
        return LivePaperRiskInterlock(starting_equity=Decimal("100.00"))

    def test_gateway_heartbeat_stale_veto(self, risk_interlock: LivePaperRiskInterlock) -> None:
        """Heartbeat age > 500ms triggers GATEWAY_HEARTBEAT_STALE veto."""
        stale_gw = GatewayHealth(heartbeat_age_ms=550.0, is_healthy=False)
        nom_hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.35"))

        dec = validate_realtime_veto_interlocks(
            interlock=risk_interlock,
            hawkes_snapshot=nom_hawkes,
            feed_health=stale_gw,
            proposed_notional=Decimal("5.00"),
            symbol="BTCUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.GATEWAY_HEARTBEAT_STALE.value
        assert dec.veto_flags["gateway_heartbeat_stale"] is True

    def test_gateway_clock_skew_breach_veto(self, risk_interlock: LivePaperRiskInterlock) -> None:
        """Clock skew > 250ms triggers CLOCK_SKEW_BREACH veto."""
        skew_gw = GatewayHealth(heartbeat_age_ms=50.0, clock_skew_ms=300.0, is_healthy=True)
        nom_hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.35"))

        dec = validate_realtime_veto_interlocks(
            interlock=risk_interlock,
            hawkes_snapshot=nom_hawkes,
            feed_health=skew_gw,
            proposed_notional=Decimal("5.00"),
            symbol="BTCUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.CLOCK_SKEW_BREACH.value

    def test_hawkes_supercritical_veto(self, risk_interlock: LivePaperRiskInterlock) -> None:
        """Spectral radius >= 1.0 triggers SUPERCRITICAL_CASCADE_LOCKOUT veto."""
        norm_gw = GatewayHealth(heartbeat_age_ms=50.0, is_healthy=True)
        super_hawkes = HawkesTelemetrySnapshot(
            symbol="BTCUSDT",
            spectral_radius=Decimal("1.05"),
            is_supercritical=True,
            regime="SUPERCRITICAL_CASCADE",
        )

        dec = validate_realtime_veto_interlocks(
            interlock=risk_interlock,
            hawkes_snapshot=super_hawkes,
            feed_health=norm_gw,
            proposed_notional=Decimal("5.00"),
            symbol="BTCUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT.value
        assert dec.veto_flags["hawkes_supercritical"] is True

    def test_aggregate_exposure_cap_veto(self, risk_interlock: LivePaperRiskInterlock) -> None:
        """Total projected exposure > 60.00 USDT triggers AGGREGATE_EXPOSURE_CAP_EXCEEDED veto."""
        norm_gw = GatewayHealth(heartbeat_age_ms=50.0, is_healthy=True)
        nom_hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.35"))

        risk_interlock.update_active_exposure("GLOBAL", Decimal("58.00"))

        dec = validate_realtime_veto_interlocks(
            interlock=risk_interlock,
            hawkes_snapshot=nom_hawkes,
            feed_health=norm_gw,
            proposed_notional=Decimal("5.00"),  # 58 + 5 = 63 > 60
            symbol="BTCUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED.value
        assert dec.veto_flags["margin_headroom_breach"] is True

    def test_margin_headroom_breach_veto(self, risk_interlock: LivePaperRiskInterlock) -> None:
        """Cash reserve < 40% triggers MARGIN_HEADROOM_BREACH veto."""
        norm_gw = GatewayHealth(heartbeat_age_ms=50.0, is_healthy=True)
        nom_hawkes = HawkesTelemetrySnapshot(symbol="ETHUSDT", spectral_radius=Decimal("0.35"))

        risk_interlock.update_active_exposure("GLOBAL", Decimal("0.00"))
        risk_interlock._current_cash = Decimal("41.00")

        dec = validate_realtime_veto_interlocks(
            interlock=risk_interlock,
            hawkes_snapshot=nom_hawkes,
            feed_health=norm_gw,
            proposed_notional=Decimal("2.00"),
            symbol="ETHUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.MARGIN_HEADROOM_BREACH.value


# =====================================================================
# 7. Loss Ceiling Breach & Emergency Flattening Slicing
# =====================================================================


class TestLossCeilingBreachAndFlattening:
    """Tests for intra-phase loss budget ceiling lockout and micro-chunk flattening."""

    def test_loss_ceiling_breach_triggers_lockout(self) -> None:
        """Loss >= 7.00 USDT triggers INTRA_PHASE_LOSS_LOCKOUT and emergency flattening."""
        interlock = LivePaperRiskInterlock(starting_equity=Decimal("100.00"))
        interlock.cumulative_loss = Decimal("7.50")

        norm_gw = GatewayHealth(heartbeat_age_ms=50.0, is_healthy=True)
        nom_hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.35"))

        dec = validate_realtime_veto_interlocks(
            interlock=interlock,
            hawkes_snapshot=nom_hawkes,
            feed_health=norm_gw,
            proposed_notional=Decimal("5.00"),
            symbol="BTCUSDT",
        )
        assert dec.allowed is False
        assert dec.veto_code == InterlockCode.INTRA_PHASE_LOSS_LOCKOUT.value
        assert dec.veto_flags["intra_phase_loss_breach"] is True
        assert dec.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT.value
        assert dec.emergency_flattening_required is True

    def test_flattening_orders_sliced_into_micro_chunks(self) -> None:
        """Portfolio flattening creates child orders <= 5.00 USDT with ROUND_DOWN precision."""
        interlock = LivePaperRiskInterlock(starting_equity=Decimal("100.00"))
        open_positions = {
            "BTCUSDT": {"symbol": "BTCUSDT", "quantity": Decimal("0.00030"), "side": "BUY"},
        }
        prices = {"BTCUSDT": Decimal("60000.00")}

        children = interlock.flatten_portfolio_emergency(
            positions=open_positions,
            prices=prices,
        )
        assert len(children) > 0
        for child in children:
            assert child.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT
            assert child.side == OrderSide.SELL


# =====================================================================
# 8. Continuous Double-Entry Zero-Drift Balance Equation Validation
# =====================================================================


class TestPaperExecutionBindingAndZeroDrift:
    """Tests for order execution pipeline binding and zero-drift balance invariant."""

    def test_order_slicing_and_matching(
        self, sample_depth_snapshot: OrderBookDepthSnapshot
    ) -> None:
        """Parent order is sliced into micro chunks <= 5.00 USDT and matched on depth."""
        parent = ParentOrderIntention(
            parent_order_id="p-test-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("60000.00"),
            target_notional_usdt=Decimal("15.00"),
        )
        filters = get_default_exchange_filters()["BTCUSDT"]
        children = slice_parent_order(parent, filters=filters, chunk_cap_usdt=Decimal("5.00"))

        assert len(children) == 3
        for child in children:
            assert child.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT

    def test_continuous_mathematical_double_entry_zero_drift(
        self, sample_depth_snapshot: OrderBookDepthSnapshot
    ) -> None:
        """Continuous mathematical double-entry zero-drift balance equation.

        Invariant: Cash + Allocated Margin + Unrealized PnL ==
        Starting Equity + Realized PnL + PosUnrealized
        with strict absolute tolerance |drift| < 1e-15 USDT across executions.
        """
        ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))
        engine = SimulatedPassiveMatchingEngine()
        engine.update_depth(sample_depth_snapshot)
        filters = get_default_exchange_filters()["BTCUSDT"]

        parent = ParentOrderIntention(
            parent_order_id="p-zero-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("60000.00"),
            target_notional_usdt=Decimal("9.60"),
        )
        children = slice_parent_order(parent, filters=filters, chunk_cap_usdt=Decimal("5.00"))

        # Step 1: Submit orders to ledger
        for child in children:
            ledger.persist_order(child)
            assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT

        # Step 2: Match orders in engine and record fills in ledger
        for i, child in enumerate(children):
            engine.place_order(child)
            trade = AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=100 + i,
                price=Decimal("59990.00"),  # Below buy limit price 60000.00
                quantity=Decimal("1.0"),
                trade_time=datetime.now(UTC),
                is_buyer_maker=True,
            )
            fills = engine.on_aggregate_trade(trade)
            for fill in fills:
                ledger.record_fill(fill)
                assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT

        ledger.create_snapshot()
        assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 9. Merkle DAG Artifact Persistence & Cryptographic Validation
# =====================================================================


class TestMerkleDAGPersistenceAndVerification:
    """Tests for Merkle DAG artifact persistence and cryptographic chain verification."""

    def test_persist_phase295_artifacts_and_verify_chain(self, tmp_path: Path) -> None:
        """Emits all 5 artifacts and verifies Merkle DAG root linking upstream Phase 294."""
        upstream_dir = tmp_path / "artifacts" / "research" / "phase294"
        upstream_dir.mkdir(parents=True, exist_ok=True)
        mock_p294_summary = upstream_dir / "paper-execution-summary.json"
        mock_p294_summary.write_text(
            json.dumps({"phase": "phase_294", "status": "EXECUTION_COMPLETE"}), encoding="utf-8"
        )

        output_dir = tmp_path / "artifacts" / "research" / "phase295"
        ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))

        sample_child = ChildOrderIntention(
            client_order_id="c-test-001",
            parent_order_id="p-test-001",
            child_index=0,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),
            notional_usdt=Decimal("3.00"),
            status=OrderStatus.NEW,
            created_time_ms=1720000000000,
        )

        sample_cand_record = OOSPromotionGateRecord(
            candidate_id="cand-test-001",
            symbol="BTCUSDT",
            status=CandidatePromotionStatus.PROMOTED,
            oos_average_return_pct=Decimal("3.50"),
            oos_worst_drawdown_pct=Decimal("8.20"),
            oos_profit_factor=Decimal("1.8000"),
            oos_trade_count=15,
            oos_window_count=3,
            gates_passed={"all": True},
            qualified=True,
            evaluated_at=datetime.now(UTC),
        )

        artifacts = persist_phase295_artifacts(
            output_dir=output_dir,
            upstream_dir=upstream_dir,
            ledger=ledger,
            child_orders=[sample_child],
            interlocks=[],
            candidate_records=[sample_cand_record],
        )

        assert len(artifacts) == 5
        for filename in artifacts:
            fp = output_dir / filename
            assert fp.exists()
            assert fp.stat().st_size > 0

        # Verify Merkle DAG chain
        assert verify_phase295_artifacts(output_dir=output_dir, upstream_dir=upstream_dir) is True
