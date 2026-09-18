"""Unit tests for Phase 270: Canary Deployment Dry-Run Runner & Micro Shadow Engine."""

from __future__ import annotations

import io
import json
import socket
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DOUBLE_ENTRY_MAX_DRIFT,
    EXPECTED_MANIFEST_V2_CANDIDATES,
    CanaryCircuitState,
    CanaryShadowExecutionEngine,
    CanaryShadowOrder,
    SqliteCanaryOrdersStore,
    SqliteCanaryShadowLedger,
    load_and_validate_canary_staging_manifest,
    run_canary_staging_simulation,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)
from autonomous_futures.paper.staging import (  # noqa: E402
    CanaryStagingManifest,
    check_fail_closed_safety_invariants,
)
from scripts.run_phase_270_canary_staging import (  # noqa: E402
    main as cli_main,
)
from scripts.run_phase_270_canary_staging import (  # noqa: E402
    run_phase_270_canary_staging,
)


@pytest.fixture
def isolated_stores(tmp_path: Path) -> tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger]:
    """Provide clean isolated SQLite stores in a temporary directory."""
    orders_path = tmp_path / "test-canary-orders.sqlite3"
    ledger_path = tmp_path / "test-canary-shadow-ledger.sqlite3"
    orders_store = SqliteCanaryOrdersStore(orders_path)
    ledger_store = SqliteCanaryShadowLedger(ledger_path)
    return orders_store, ledger_store


@pytest.fixture
def valid_manifest() -> CanaryStagingManifest:
    """Load and return verified Phase 269 Canary Staging Manifest."""
    manifest, _ = load_and_validate_canary_staging_manifest(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
    )
    return manifest


class TestPhase270ManifestAndCandidateValidation:
    """Validate dynamic ingestion of Canary Staging Manifest and Candidate Provenance."""

    def test_load_and_validate_verified_manifest(
        self, valid_manifest: CanaryStagingManifest
    ) -> None:
        assert valid_manifest.manifest_version >= 2
        assert valid_manifest.registry_version >= 2
        assert valid_manifest.staging_promotion_state == "canary_staged"
        assert set(valid_manifest.candidates.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        for sym, exp_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            cand = valid_manifest.candidates[sym]
            assert cand.candidate_id == exp_id
            assert cand.staging_promotion_state == "canary_staged"
            assert len(cand.candidate_artifact_hash) == 64
            assert len(cand.qualification_hash) == 64
            assert cand.allocated_risk_limits.allocated_margin_usdt == Decimal("20.0000")

    def test_tampered_manifest_hash_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["manifest_hash"] = "0" * 64
        tampered_file = tmp_path / "tampered-manifest.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation, match="integrity check failed"):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_tampered_signature_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["cryptographic_signature"] = "f" * 64
        tampered_file = tmp_path / "tampered-sig.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation, match="integrity check failed"):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_missing_candidate_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        del raw["candidates"]["SOLUSDT"]
        tampered_file = tmp_path / "missing-cand.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_manifest_promotion_state_rejection(self, tmp_path: Path) -> None:
        """Reject manifests where staging_promotion_state is not 'canary_staged'."""
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["staging_promotion_state"] = "rejected"
        tampered_file = tmp_path / "rejected-manifest.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(
            DomainViolation, match="integrity check failed|expected 'canary_staged'"
        ):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_candidate_promotion_state_rejection(self, tmp_path: Path) -> None:
        """Reject candidates whose staging_promotion_state is not 'canary_staged'."""
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["candidates"]["BTCUSDT"]["staging_promotion_state"] = "rejected"
        tampered_file = tmp_path / "rejected-cand.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(
            DomainViolation, match="integrity check failed|expected 'canary_staged'"
        ):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_unexpected_candidate_rejection(self, tmp_path: Path) -> None:
        """Reject manifests with unauthorized additional candidate symbols."""
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        # Copy BTCUSDT to DOGEUSDT
        raw["candidates"]["DOGEUSDT"] = dict(raw["candidates"]["BTCUSDT"])
        raw["candidates"]["DOGEUSDT"]["symbol"] = "DOGEUSDT"
        raw["candidates"]["DOGEUSDT"]["candidate_id"] = "cand-dogeusdt-dcb-001"
        tampered_file = tmp_path / "extra-cand.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation, match="integrity check failed|Unexpected candidate"):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_missing_registry_path_rejection(self, tmp_path: Path) -> None:
        """Explicit nonexistent registry path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Candidate Registry not found"):
            load_and_validate_canary_staging_manifest(
                DEFAULT_CANARY_STAGING_MANIFEST_PATH,
                registry_path=tmp_path / "nonexistent-registry.json",
            )

    def test_candidate_qualification_hash_mismatch_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tampered qualification hash raises DomainViolation."""
        from autonomous_futures.paper import canary_staging as cs_mod

        original_fn = cs_mod.read_creator_candidate_qualification_artifact

        def mock_read_qual(p: Any) -> Any:
            orig = original_fn(p)
            return orig.model_copy(update={"qualification_hash": "0" * 64})

        monkeypatch.setattr(cs_mod, "read_creator_candidate_qualification_artifact", mock_read_qual)

        with pytest.raises(DomainViolation, match="Qualification hash mismatch"):
            load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)

    def test_missing_candidate_artifact_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing candidate artifact file raises FileNotFoundError."""
        from autonomous_futures.paper import canary_staging as cs_mod

        # Point artifact path to non-existent
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["candidates"]["BTCUSDT"]["artifact_path"] = "nonexistent/candidate.json"
        # Temporarily bypass manifest integrity to reach candidate file check
        monkeypatch.setattr(cs_mod, "verify_staging_manifest_integrity", lambda m: (True, []))
        tampered_file = tmp_path / "missing-art.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(FileNotFoundError, match="Candidate artifact file missing"):
            load_and_validate_canary_staging_manifest(tampered_file)


class TestPhase270MicroNotionalAndMarginGuardrails:
    """Validate micro notional sizing (<= 5.00 USDT) and aggregate margin guardrails."""

    def test_micro_notional_cap_acceptance_and_rejection(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
            max_micro_notional=Decimal("5.00"),
        )

        # Order within micro notional: 0.00008 * 60,000 = 4.80 USDT <= 5.00 USDT
        ok, msg, order = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00008"),
            limit_price=Decimal("60000.00"),
        )
        assert ok is True
        assert msg == "ORDER_ACCEPTED"
        assert order is not None
        assert order.micro_notional == Decimal("4.80")
        assert order.status == "PENDING"

        # Order exceeding micro notional: 0.0001 * 60,000 = 6.00 USDT > 5.00 USDT
        ok2, msg2, order2 = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.002"),
            limit_price=Decimal("3000.00"),  # 6.00 USDT
        )
        assert ok2 is False
        assert "EXCEEDS_MICRO_NOTIONAL_CAP" in msg2
        assert order2 is None

    def test_aggregate_margin_utilization_and_reserve_buffer_ceiling(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        # Starting equity 10.00 USDT: 60% max utilization = 6.00 USDT
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
            starting_equity=Decimal("10.00"),
            max_micro_notional=Decimal("5.00"),
            max_aggregate_margin_utilization=Decimal("0.60"),
            min_aggregate_reserve_buffer=Decimal("0.40"),
        )

        # First order 4.00 USDT -> 40% margin utilization <= 60%
        ok1, _, order1 = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.0001"),
            limit_price=Decimal("40000.00"),
        )
        assert ok1 is True
        assert order1 is not None
        engine.execute_shadow_fill(order1.order_id, Decimal("40000.00"))

        # Second order 3.00 USDT -> total locked would be 7.00 / 10.00 = 70% > 60%
        ok2, msg2, order2 = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            limit_price=Decimal("3000.00"),
        )
        assert ok2 is False
        assert "MARGIN_UTILIZATION_CEILING_EXCEEDED" in msg2 or "RESERVE_BUFFER_BREACH" in msg2
        assert order2 is None

    def test_single_position_invariant_per_symbol(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        ok1, _, order1 = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60000.00"),
        )
        assert ok1 is True
        assert order1 is not None

        # Attempt duplicate pending order on same symbol
        ok_dup, msg_dup, _ = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60000.00"),
        )
        assert ok_dup is False
        assert "SINGLE_POSITION_INVARIANT_VIOLATION" in msg_dup

        # Fill first order to establish active position
        engine.execute_shadow_fill(order1.order_id, Decimal("60000.00"))

        # Attempt new order while position is open
        ok_pos, msg_pos, _ = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60000.00"),
        )
        assert ok_pos is False
        assert "SINGLE_POSITION_INVARIANT_VIOLATION" in msg_pos

        # After closing position, new order is allowed
        engine.close_shadow_position("BTCUSDT", Decimal("60500.00"))
        ok_after, _, _ = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60500.00"),
        )
        assert ok_after is True

    def test_starting_equity_zero_or_negative_rejection(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Reject engines initialized with zero or negative equity."""
        orders_store, ledger_store = isolated_stores
        with pytest.raises(DomainViolation, match="Starting equity must be strictly positive"):
            CanaryShadowExecutionEngine(
                manifest=valid_manifest,
                orders_store=orders_store,
                ledger_store=ledger_store,
                starting_equity=Decimal("0.00"),
            )
        with pytest.raises(DomainViolation, match="Starting equity must be strictly positive"):
            CanaryShadowExecutionEngine(
                manifest=valid_manifest,
                orders_store=orders_store,
                ledger_store=ledger_store,
                starting_equity=Decimal("-50.00"),
            )

    def test_unauthorized_symbol_rejection(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Reject order submissions for unstaged symbols."""
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )
        ok, msg, order = engine.submit_shadow_order(
            candidate_id="cand-doge-001",
            symbol="DOGEUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("10.0"),
            limit_price=Decimal("0.10"),
        )
        assert ok is False
        assert "UNAUTHORIZED_SYMBOL" in msg
        assert order is None

    def test_mismatched_candidate_id_rejection(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Reject order submissions where candidate_id does not match manifest entry for symbol."""
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )
        ok, msg, order = engine.submit_shadow_order(
            candidate_id="cand-wrong-id",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00008"),
            limit_price=Decimal("60000.00"),
        )
        assert ok is False
        assert "CANDIDATE_ID_MISMATCH" in msg
        assert order is None


class TestPhase270SqliteStoresAndPersistence:
    """Validate isolated durable persistence in canary-orders and shadow-ledger SQLite stores."""

    def test_order_and_fill_lifecycle_persisted_in_sqlite(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        ok, _, order = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            limit_price=Decimal("3000.00"),
        )
        assert ok is True
        assert order is not None
        assert orders_store.count_orders() == 1
        assert len(orders_store.get_pending_orders("ETHUSDT")) == 1

        fill_ok, _, fill = engine.execute_shadow_fill(order.order_id, Decimal("3000.00"))
        assert fill_ok is True
        assert fill is not None
        assert orders_store.count_fills() == 1
        assert len(orders_store.get_pending_orders("ETHUSDT")) == 0

        # Position is open
        open_positions = ledger_store.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].symbol == "ETHUSDT"
        assert open_positions[0].quantity == Decimal("0.001")

        # Close position
        close_ok, _, close_fill = engine.close_shadow_position("ETHUSDT", Decimal("3100.00"))
        assert close_ok is True
        assert close_fill is not None
        assert orders_store.count_orders() == 2
        assert orders_store.count_fills() == 2
        assert orders_store.verify_referential_integrity() == (True, 0)
        assert len(ledger_store.get_open_positions()) == 0

        # Verify unlocked
        assert orders_store.verify_unlocked() is True
        assert ledger_store.verify_unlocked() is True


class TestPhase270Tier1SoftDeescalation:
    """Validate Tier 1 soft de-escalation freeze on market anomalies."""

    def test_spread_expansion_freezes_new_orders(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # Normal condition
        triggered = engine.evaluate_feed_telemetry(
            symbol="BTCUSDT",
            spread_bps=Decimal("10.0"),  # < 20 bps
            volatility_ratio=Decimal("1.2"),
            heartbeat_age_sec=1.0,
        )
        assert triggered is False
        assert engine.circuit_state == CanaryCircuitState.NORMAL

        # Spread expansion anomaly (25 bps >= 20 bps)
        triggered2 = engine.evaluate_feed_telemetry(
            symbol="BTCUSDT",
            spread_bps=Decimal("25.0"),
            volatility_ratio=Decimal("1.2"),
            heartbeat_age_sec=1.0,
        )
        assert triggered2 is True
        assert engine.circuit_state == CanaryCircuitState.TIER1_SOFT_DEESCALATION

        # New order attempts must now be frozen/rejected
        ok, msg, _ = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60000.00"),
        )
        assert ok is False
        assert "CIRCUIT_TIER1_SOFT_DEESCALATION_FREEZE" in msg

    def test_volatility_surge_freezes_new_orders(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # Volatility spike: 3.0x >= 2.5x threshold
        triggered = engine.evaluate_feed_telemetry(
            symbol="ETHUSDT",
            spread_bps=Decimal("5.0"),
            volatility_ratio=Decimal("3.0"),
            heartbeat_age_sec=1.0,
        )
        assert triggered is True
        assert engine.circuit_state == CanaryCircuitState.TIER1_SOFT_DEESCALATION

    def test_heartbeat_timeout_freezes_new_orders(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # Feed timeout: 12.0s >= 10.0s
        triggered = engine.evaluate_feed_telemetry(
            symbol="SOLUSDT",
            spread_bps=Decimal("5.0"),
            volatility_ratio=Decimal("1.0"),
            heartbeat_age_sec=12.0,
        )
        assert triggered is True
        assert engine.circuit_state == CanaryCircuitState.TIER1_SOFT_DEESCALATION


class TestPhase270Tier2HardAbortAndLiquidations:
    """Validate Tier 2 hard abort: order cancellation, immediate liquidation, and drift shutdown."""

    def test_drawdown_breach_triggers_hard_abort_and_liquidation(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        # Starting equity 100 USDT, drawdown limit 2% (2.00 USDT)
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
            starting_equity=Decimal("100.00"),
            tier2_max_drawdown=Decimal("0.02"),
        )

        # Open a position of 5.00 USDT notional (e.g. 0.0001 BTC at 50,000)
        _, _, order = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.0001"),
            limit_price=Decimal("50000.00"),
        )
        assert order is not None
        engine.execute_shadow_fill(order.order_id, Decimal("50000.00"))

        # Also submit a pending order on ETHUSDT
        _, _, eth_order = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            limit_price=Decimal("3000.00"),
        )
        assert eth_order is not None

        # Price drops significantly, causing > 2.00% portfolio drawdown
        # 0.0001 BTC drops from 50,000 to 25,000 -> loss = 2.50 USDT on 100.00 USDT = 2.50% drawdown
        engine.update_mark_price("BTCUSDT", Decimal("25000.00"))

        assert engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT
        assert len(engine.open_orders) == 0
        assert len(engine.open_positions) == 0
        assert engine.cancelled_orders_count >= 1
        assert engine.liquidations_count == 1
        assert len(engine.kill_switch_events) == 1
        assert engine.kill_switch_events[0].trigger_type == "DRAWDOWN_BREACH"

    def test_accounting_drift_triggers_immediate_hard_abort(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # Inject synthetic drift > 1e-15 USDT
        engine.simulate_adverse_drift(Decimal("0.05"))

        assert engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT
        assert len(engine.kill_switch_events) == 1
        assert engine.kill_switch_events[0].trigger_type == "ACCOUNTING_DRIFT"

    def test_manual_kill_switch_trigger(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        ev = engine.trigger_emergency_kill_switch(reason="Manual test trigger")
        assert engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT
        assert ev.trigger_type == "MANUAL_CLI_TRIGGER"
        assert ev.tier == 2


class TestPhase270ExactDoubleEntryAccounting:
    """Validate mathematical zero-drift double-entry balance reconciliation across trades."""

    def test_round_trip_reconciliation_exact_zero_drift(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
            starting_equity=Decimal("100.00"),
        )

        # Initial state: cash = 100.00, realized_pnl = 0
        drift, zero_drift = engine.reconcile_accounting()
        assert zero_drift is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        # Trade 1: Open and Close BTCUSDT
        _, _, o1 = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00008"),
            limit_price=Decimal("60000.00"),
        )
        assert o1 is not None
        engine.execute_shadow_fill(o1.order_id, Decimal("60000.00"))
        drift, zero_drift = engine.reconcile_accounting()
        assert zero_drift is True

        engine.close_shadow_position("BTCUSDT", Decimal("61000.00"))
        drift, zero_drift = engine.reconcile_accounting()
        assert zero_drift is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        # Trade 2: Open and Close ETHUSDT
        _, _, o2 = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.0015"),
            limit_price=Decimal("3000.00"),
        )
        assert o2 is not None
        engine.execute_shadow_fill(o2.order_id, Decimal("3000.00"))
        engine.close_shadow_position("ETHUSDT", Decimal("2950.00"))

        drift, zero_drift = engine.reconcile_accounting()
        assert zero_drift is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        assert engine.cash == engine.starting_equity + engine.realized_pnl


class TestPhase270FailClosedSafetyAndZeroLeakage:
    """Validate strict fail-closed safety invariants and zero credential leakage."""

    def test_fail_closed_safety_invariants(self) -> None:
        inv = check_fail_closed_safety_invariants()
        assert inv["api_keys_loaded"] == 0
        assert inv["execution_authority"] is False
        assert inv["exchange_access"] is False
        assert inv["orders"] == 0
        assert inv["zero_secret_leakage"] is True

    def test_offline_containment_no_network_calls(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify execution occurs completely offline with zero external network attempts."""

        def forbidden_connect(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("NETWORK CALL ATTEMPTED IN OFFLINE SHADOW ENGINE")

        monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        ok, _, order = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00005"),
            limit_price=Decimal("60000.00"),
        )
        assert ok is True
        assert order is not None
        engine.execute_shadow_fill(order.order_id, Decimal("60000.00"))
        engine.close_shadow_position("BTCUSDT", Decimal("60500.00"))

    def test_zero_secret_leakage_in_artifacts(self, tmp_path: Path) -> None:
        summary, _, _ = run_canary_staging_simulation(
            output_dir=tmp_path / "artifacts",
            max_ticks=10,
        )
        assert summary.safety_invariants["zero_secret_leakage"] is True
        assert summary.safety_invariants["api_keys_loaded"] == 0
        assert summary.safety_invariants["orders"] == 0


class TestPhase270CliRunnerAndSimulation:
    """Validate CLI execution runner and synthetic anomaly injection flags."""

    def test_cli_runner_nominal_run(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_nominal"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=15,
        )
        assert rc == 0
        assert (out_dir / "canary-orders.sqlite3").is_file()
        assert (out_dir / "canary-shadow-ledger.sqlite3").is_file()
        assert (out_dir / "canary-summary.json").is_file()
        assert (out_dir / "paper-summary.json").is_file()
        assert (out_dir / "canary-execution-report.json").is_file()

        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "NORMAL"
        assert data["zero_balance_drift"] is True
        assert data["margin_guardrails_compliant"] is True
        assert data["orders_count"] > 0
        assert data["fills_count"] > 0

    def test_cli_runner_trigger_kill_switch(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_kill_switch"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            trigger_kill_switch=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER2_HARD_ABORT"
        assert len(data["kill_switch_events"]) == 1

    def test_cli_runner_simulate_adverse_drift(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_drift"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=15,
            simulate_adverse_drift=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER2_HARD_ABORT"
        assert len(data["kill_switch_events"]) >= 1

    def test_cli_runner_simulate_spread_expansion(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_spread"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=10,
            simulate_spread_expansion=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER1_SOFT_DEESCALATION"
        assert len(data["kill_switch_events"]) >= 1
        assert data["kill_switch_events"][0]["trigger_type"] == "SPREAD_EXPANSION"

    def test_cli_runner_simulate_volatility_surge(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_volatility"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=10,
            simulate_volatility_surge=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER1_SOFT_DEESCALATION"
        assert len(data["kill_switch_events"]) >= 1
        assert data["kill_switch_events"][0]["trigger_type"] == "VOLATILITY_REGIME_SHIFT"

    def test_cli_runner_simulate_feed_timeout(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_timeout"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=10,
            simulate_feed_timeout=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER1_SOFT_DEESCALATION"
        assert len(data["kill_switch_events"]) >= 1
        assert data["kill_switch_events"][0]["trigger_type"] == "FEED_HEARTBEAT_TIMEOUT"

    def test_cli_runner_simulate_drawdown_breach(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_drawdown"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=20,
            simulate_drawdown_breach=True,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["circuit_state"] == "TIER2_HARD_ABORT"
        assert len(data["kill_switch_events"]) >= 1
        assert any(e["trigger_type"] == "DRAWDOWN_BREACH" for e in data["kill_switch_events"])

    def test_cli_runner_symbols_filter_valid(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_symbols"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=15,
            symbols=["BTCUSDT"],
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["zero_balance_drift"] is True
        assert data["orders_count"] > 0

    def test_cli_runner_symbols_filter_invalid_rejection(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_invalid_sym"
        with pytest.raises(DomainViolation, match="not among staged candidates"):
            run_phase_270_canary_staging(
                output_dir=out_dir,
                max_ticks=10,
                symbols=["DOGEUSDT"],
            )

    def test_cli_runner_zero_ticks_dry_run(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_zero_ticks"
        rc = run_phase_270_canary_staging(
            output_dir=out_dir,
            max_ticks=0,
        )
        assert rc == 0
        with open(out_dir / "canary-summary.json") as f:
            data = json.load(f)
        assert data["orders_count"] == 0
        assert data["fills_count"] == 0
        assert data["zero_balance_drift"] is True

    def test_cli_runner_negative_ticks_rejection(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase270_neg_ticks"
        with pytest.raises(DomainViolation, match="max_ticks must be non-negative"):
            run_phase_270_canary_staging(
                output_dir=out_dir,
                max_ticks=-5,
            )

    def test_cli_main_stdout_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out_dir = tmp_path / "phase270_json"
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        rc = cli_main(["--output-dir", str(out_dir), "--max-ticks", "10", "--json"])
        assert rc == 0
        output = captured.getvalue()
        parsed = json.loads(output)
        assert parsed["phase"] == "phase_270"
        assert "portfolio" in parsed or "starting_capital_usdt" in parsed


class TestPhase270AdversarialHardening:
    """Adversarial stress tests for referential integrity, idempotency, batching, and isolation."""

    def test_referential_integrity_and_zero_orphaned_fills(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify all fills (entry, close, and liquidation) have a valid parent shadow order."""
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # 1. Normal entry and exit cycle
        ok, _, o1 = engine.submit_shadow_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00008"),
            limit_price=Decimal("60000.00"),
        )
        assert ok is True and o1 is not None
        engine.execute_shadow_fill(o1.order_id, Decimal("60000.00"))
        engine.close_shadow_position("BTCUSDT", Decimal("60500.00"))

        # 2. Emergency liquidation cycle
        ok2, _, o2 = engine.submit_shadow_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            limit_price=Decimal("3000.00"),
        )
        assert ok2 is True and o2 is not None
        engine.execute_shadow_fill(o2.order_id, Decimal("3000.00"))
        engine.trigger_tier2_hard_abort(
            "EMERGENCY_TEST", "Testing referential integrity on liquidation"
        )

        # Verify exact referential integrity in SQLite
        ref_ok, orphans = orders_store.verify_referential_integrity()
        assert ref_ok is True
        assert orphans == 0
        assert orders_store.count_orders() == 4  # o1 entry, o1 exit, o2 entry, o2 liquidation
        assert orders_store.count_fills() == 4
        assert engine.orders_generated_count == 4
        assert engine.fills_executed_count == 4

    def test_counts_synchronization_orders_and_fills(self, tmp_path: Path) -> None:
        """Verify complete sync between SQLite stores, in-memory engine, and JSON reports."""
        out_dir = tmp_path / "sync_test"
        summary, ledger_db, orders_db = run_canary_staging_simulation(
            output_dir=out_dir,
            max_ticks=15,
        )

        orders_store = SqliteCanaryOrdersStore(orders_db)
        ledger_store = SqliteCanaryShadowLedger(ledger_db)

        # Orders count and fills count must match exactly
        assert orders_store.count_orders() == summary.orders_count
        assert orders_store.count_fills() == summary.fills_count
        ref_ok, orphans = orders_store.verify_referential_integrity()
        assert ref_ok is True
        assert orphans == 0

        # Ledger marks must have zero drift
        ledger_ok, max_drift = ledger_store.verify_double_entry_integrity()
        assert ledger_ok is True
        assert max_drift < Decimal("1e-15")

    def test_tier2_hard_abort_idempotency(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify Tier 2 hard abort is strictly idempotent when invoked repeatedly."""
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
        )

        # Open a position first
        ok, _, o = engine.submit_shadow_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.02"),
            limit_price=Decimal("150.00"),
        )
        assert ok is True and o is not None
        engine.execute_shadow_fill(o.order_id, Decimal("150.00"))

        # Trigger Tier 2 once
        ev1 = engine.trigger_emergency_kill_switch(reason="First trigger")
        assert engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT
        assert len(engine.kill_switch_events) == 1
        assert engine.liquidations_count == 1

        # Trigger Tier 2 second time
        ev2 = engine.trigger_emergency_kill_switch(reason="Second trigger (duplicate)")
        assert engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT
        # Must return the existing Tier 2 event without duplicating
        assert ev2.event_id == ev1.event_id
        assert len(engine.kill_switch_events) == 1
        assert engine.liquidations_count == 1
        assert ledger_store.count_kill_switch_events() == 1

    def test_high_frequency_batch_order_generation(
        self,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify high-frequency batch order and fill insertion rate (> 10,000 orders/sec)."""
        import time

        orders_store, _ = isolated_stores
        batch_size = 1000
        orders = [
            CanaryShadowOrder(
                order_id=f"ord-batch-{i}",
                client_order_id=f"c-batch-{i}",
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.00008"),
                limit_price=Decimal("60000.00"),
                micro_notional=Decimal("4.80"),
                status="PENDING",
                created_at="2026-09-18T00:00:00Z",
                updated_at="2026-09-18T00:00:00Z",
            )
            for i in range(batch_size)
        ]

        t0 = time.perf_counter()
        orders_store.insert_orders(orders)
        elapsed = time.perf_counter() - t0

        assert orders_store.count_orders() == batch_size
        assert elapsed < 1.0  # Must insert 1000 orders in under 1 second (> 1000/sec on SQLite)

    def test_sqlite_crash_and_lock_release(
        self,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify SQLite constraint or operational errors release all locks immediately."""
        import sqlite3

        orders_store, _ = isolated_stores
        # Insert initial order
        order = CanaryShadowOrder(
            order_id="ord-unique-1",
            client_order_id="c-unique-1",
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00008"),
            limit_price=Decimal("60000.00"),
            micro_notional=Decimal("4.80"),
            status="PENDING",
            created_at="2026-09-18T00:00:00Z",
            updated_at="2026-09-18T00:00:00Z",
        )
        orders_store.insert_order(order)

        # Attempt to insert identical order violating PRIMARY KEY constraint
        with pytest.raises(sqlite3.IntegrityError):
            orders_store.insert_order(order)

        # Verify database is completely unlocked and operational immediately
        assert orders_store.verify_unlocked() is True
        assert orders_store.count_orders() == 1

    def test_floating_point_precision_and_exact_zero_drift(
        self,
        valid_manifest: CanaryStagingManifest,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify exact zero-drift balance reconciliation with arbitrary fractional values."""
        orders_store, ledger_store = isolated_stores
        engine = CanaryShadowExecutionEngine(
            manifest=valid_manifest,
            orders_store=orders_store,
            ledger_store=ledger_store,
            starting_equity=Decimal("100.00"),
        )

        # Run 5 alternating trades with non-trivial fractional prices
        trade_params = [
            ("BTCUSDT", "cand-btcusdt-dcb-002", "0.00008333", "59999.99", "60123.45"),
            ("ETHUSDT", "cand-ethusdt-dcb-003", "0.00161234", "3099.75", "3050.25"),
            ("SOLUSDT", "cand-solusdt-rgb-001", "0.03312345", "150.85", "152.40"),
        ]

        for sym, cand_id, qty_s, entry_px_s, exit_px_s in trade_params:
            ok, _, o = engine.submit_shadow_order(
                candidate_id=cand_id,
                symbol=sym,
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal(qty_s),
                limit_price=Decimal(entry_px_s),
            )
            assert ok is True and o is not None
            engine.execute_shadow_fill(o.order_id, Decimal(entry_px_s))
            drift, zero_drift = engine.reconcile_accounting()
            assert zero_drift is True
            assert drift < Decimal("1e-15")

            engine.close_shadow_position(sym, Decimal(exit_px_s))
            drift, zero_drift = engine.reconcile_accounting()
            assert zero_drift is True
            assert drift < Decimal("1e-15")

        summary = engine.get_summary()
        assert summary.zero_balance_drift is True
        assert summary.drift_usdt < Decimal("1e-15")
        assert summary.final_cash_usdt == summary.starting_capital_usdt + summary.realized_pnl_usdt

    def test_clean_slate_isolation_across_simulation_runs(self, tmp_path: Path) -> None:
        """Verify repeated simulation on same directory leaves fresh isolated state."""
        import sqlite3

        out_dir = tmp_path / "repeated_run"

        # Run 1
        run_canary_staging_simulation(output_dir=out_dir, max_ticks=10)
        # Run 2 on same output_dir
        summary2, ledger_db2, orders_db2 = run_canary_staging_simulation(
            output_dir=out_dir, max_ticks=15
        )

        with sqlite3.connect(ledger_db2) as conn:
            cur = conn.cursor()
            deposits = cur.execute(
                "SELECT COUNT(*) FROM canary_shadow_ledger_events WHERE event = 'INITIAL_DEPOSIT'"
            ).fetchone()[0]
            assert deposits == 1, f"Expected exactly 1 INITIAL_DEPOSIT, got {deposits}"

        orders_store = SqliteCanaryOrdersStore(orders_db2)
        assert orders_store.count_orders() == summary2.orders_count
        assert orders_store.count_fills() == summary2.fills_count

    def test_foreign_key_constraint_prevents_orphaned_fill(
        self,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify SQLite foreign key enforcement rejects orphaned fills at the
        database engine level.
        """
        import sqlite3

        from autonomous_futures.paper.canary_staging import CanaryShadowFill

        orders_store, _ = isolated_stores
        orphaned_fill = CanaryShadowFill(
            fill_id="fill-orphan-1",
            order_id="ord-nonexistent",
            client_order_id="c-orphan-1",
            symbol="BTCUSDT",
            side="BUY",
            fill_price=Decimal("60000.00"),
            fill_quantity=Decimal("0.00008"),
            fee_usdt=Decimal("0.00192"),
            slippage_usdt=Decimal("0.00096"),
            realized_pnl=Decimal("-0.00192"),
            filled_at="2026-09-18T00:00:00Z",
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            orders_store.insert_fill(orphaned_fill)

    def test_concurrent_multithreaded_order_and_fill_insertion(
        self,
        isolated_stores: tuple[SqliteCanaryOrdersStore, SqliteCanaryShadowLedger],
    ) -> None:
        """Verify high concurrency multithreaded order and fill insertions without lock errors."""
        import concurrent.futures

        from autonomous_futures.paper.canary_staging import CanaryShadowFill

        orders_store, _ = isolated_stores
        num_threads = 6
        orders_per_thread = 10

        def worker(thread_idx: int) -> int:
            for i in range(orders_per_thread):
                oid = f"ord-th-{thread_idx}-{i}"
                cid = f"cid-th-{thread_idx}-{i}"
                order = CanaryShadowOrder(
                    order_id=oid,
                    client_order_id=cid,
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=Decimal("0.00008"),
                    limit_price=Decimal("60000.00"),
                    micro_notional=Decimal("4.80"),
                    status="FILLED",
                    created_at="2026-09-18T00:00:00Z",
                    updated_at="2026-09-18T00:00:00Z",
                )
                orders_store.insert_order(order)
                fill = CanaryShadowFill(
                    fill_id=f"fill-th-{thread_idx}-{i}",
                    order_id=oid,
                    client_order_id=cid,
                    symbol="BTCUSDT",
                    side="BUY",
                    fill_price=Decimal("60000.00"),
                    fill_quantity=Decimal("0.00008"),
                    fee_usdt=Decimal("0.00192"),
                    slippage_usdt=Decimal("0.00096"),
                    realized_pnl=Decimal("-0.00192"),
                    filled_at="2026-09-18T00:00:00Z",
                )
                orders_store.insert_fill(fill)
            return orders_per_thread

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, t) for t in range(num_threads)]
            results = [f.result() for f in futures]

        total_expected = num_threads * orders_per_thread
        assert sum(results) == total_expected
        assert orders_store.count_orders() == total_expected
        assert orders_store.count_fills() == total_expected
        ref_ok, orphans = orders_store.verify_referential_integrity()
        assert ref_ok is True
        assert orphans == 0
        assert orders_store.verify_unlocked() is True
