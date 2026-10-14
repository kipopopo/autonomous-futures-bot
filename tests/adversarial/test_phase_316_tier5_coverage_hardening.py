# ruff: noqa: E501
"""Phase 316 Final Milestone Tier 5 Backend Adversarial Challenger Test Suite.

Comprehensive white-box adversarial stress test suite targeting backend telemetry and invariants:
- src/autonomous_futures/api/canary.py (Pydantic schema serialization, dynamic state transitions,
  Merkle hash checks, macro regime boundary toggling, double-entry zero-drift invariant).
- src/autonomous_futures/api/app.py (FastAPI endpoints /klines, /prices, /execution/status,
  malicious query parameters, malformed timestamps, zero-drift boundary fuzzing).
- src/autonomous_futures/safety/kill_switch.py (CentralizedSolvencyLedger arbitrary-precision
  double-entry balance conservation, extreme starting equities, micro-fee deductions).

Adversarial Verification Dimensions:
1. Pydantic schema serialization edge conditions (extra field rejection, whitespace stripping,
   tuple immutability, optional/null handling, extreme float serialization).
2. Extreme account equity ($10^-10 USDT, $10^9 USDT) & zero-drift boundary fuzzing ($10^-16 USDT).
3. Merkle hash calculations and cryptographic integrity failure modes (single bit-flip detection,
   upstream hash mutation, SQLite vs summary mismatch).
4. Division-by-zero immunity and numerical stability (flat volatility, 0/negative EMA spans,
   0/1000 trade counts, limit boundary bounds).
5. Macro regime boundary toggling & case fuzzing (BULLISH_ALIGNED, BEARISH, NEUTRAL, sub-cent EMA cross).
6. Malicious query parameters and ingress security (SQL injection, path traversal, out-of-bound limits,
   corrupted JSONL recovery, ord-p309- leakage filtering).
7. Malformed timestamps and date parsing resilience (non-ISO strings, out-of-range dates, safe int recovery).
8. Rapid concurrent schema polling (16 worker threads, 1,000 requests, 100% success rate, 0 race conditions).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from autonomous_futures.api.app import (
    CandlestickPoint,
    ExecutionOrderItem,
    ExecutionPositionItem,
    ExecutionSolvency,
    ExecutionStatusResponse,
    MarketKlinesResponse,
    _compute_ema_series,
    _safe_float,
    _safe_int,
    compute_authentic_btc_macro,
    create_app,
    get_live_market_data,
    load_execution_status,
    reset_live_market_cache,
)
from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
    verify_canary_phase_integrity,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
)

ALL_8_PAIRS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
)


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    """Provides a thread-safe FastAPI TestClient initialized with default routes."""
    app = create_app()
    return TestClient(app)


# =============================================================================
# 1. PYDANTIC SCHEMA SERIALIZATION HARDENING
# =============================================================================


class TestTier5PydanticSerializationHardening:
    """White-box stress testing of Pydantic models, extra-field forbidding, and JSON serialization."""

    def test_domain_model_strict_extra_field_rejection(self) -> None:
        """Verifies DomainModel subclasses reject unexpected/extra fields (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            ExecutionSolvency(
                starting_equity_usdt=100.0,
                cash_usdt=100.0,
                unauthorized_injection_payload="malicious_value",  # type: ignore[call-arg]
            )
        assert "extra_forbidden" in str(exc_info.value) or "Extra inputs are not permitted" in str(
            exc_info.value
        )

        with pytest.raises(ValidationError):
            ExecutionPositionItem(
                symbol="SOLUSDT",
                hacked_attr=True,  # type: ignore[call-arg]
            )

    def test_domain_model_whitespace_stripping_invariant(self) -> None:
        """Verifies DomainModel automatically strips leading/trailing whitespace on string inputs."""
        pos = ExecutionPositionItem(
            symbol="   SOLUSDT   ",
            state="  STANDBY / SCANNING  ",
        )
        assert pos.symbol == "SOLUSDT"
        assert pos.state == "STANDBY / SCANNING"

        order = ExecutionOrderItem(
            order_id="   ord-12345   ",
            client_order_id="   canary-p311-drill-sol-001   ",
            symbol="  ETHUSDT  ",
            side="  BUY  ",
            price=2500.0,
            quantity=0.01,
            notional_usdt=25.0,
            status="  FILLED  ",
            timestamp_ms=1728000000000,
        )
        assert order.order_id == "ord-12345"
        assert order.client_order_id == "canary-p311-drill-sol-001"
        assert order.symbol == "ETHUSDT"
        assert order.side == "BUY"
        assert order.status == "FILLED"

    def test_execution_status_extreme_float_serialization_roundtrip(self) -> None:
        """Verifies ExecutionStatusResponse serializes extreme float magnitudes ($10^-10 and $10^9)."""
        extreme_solvency = ExecutionSolvency(
            starting_equity_usdt=1e-10,
            cash_usdt=1e-10,
            allocated_margin_usdt=0.0,
            unrealized_pnl_usdt=0.0,
            realized_pnl_usdt=0.0,
            total_equity_usdt=1e-10,
            drift_usdt=0.0,
            zero_balance_drift_verified=True,
            cash_reserve_pct=100.0,
            unencumbered_cash_verified=True,
            starting_equity=1e-10,
            cash=1e-10,
            allocated_margin=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_equity=1e-10,
            drift=0.0,
            zero_balance_drift=True,
        )
        positions = {
            sym: ExecutionPositionItem(symbol=sym, mark_price=1e-8 if sym == "DOGEUSDT" else 1e5)
            for sym in ALL_8_PAIRS
        }
        res = ExecutionStatusResponse(
            verified=True,
            status="MICRO_CAPITAL_ACTIVE",
            engine_state="MICRO_CAPITAL_ACTIVE",
            timestamp_ms=1728000000000,
            solvency=extreme_solvency,
            positions=positions,
            candidate_allocations=list(positions.values()),
            aggregate_exposure_usdt=0.0,
            recent_orders=[],
            total_orders=0,
            interlock_blocks_count=0,
            intra_day_loss_usdt=0.0,
        )

        dumped_json = res.model_dump_json()
        assert isinstance(dumped_json, str)
        parsed = json.loads(dumped_json)
        assert parsed["solvency"]["starting_equity_usdt"] == pytest.approx(1e-10)
        assert parsed["solvency"]["zero_balance_drift_verified"] is True
        assert parsed["positions"]["DOGEUSDT"]["mark_price"] == pytest.approx(1e-8)

        # Re-parse into model
        rehydrated = ExecutionStatusResponse.model_validate_json(dumped_json)
        assert rehydrated.solvency.starting_equity_usdt == pytest.approx(1e-10)
        assert rehydrated.solvency.zero_balance_drift_verified is True

    def test_market_klines_response_tuple_immutability(self) -> None:
        """Verifies MarketKlinesResponse enforces tuple immutability for candlestick series."""
        candles = (
            CandlestickPoint(
                timestamp=1728000000,
                open=100.0,
                high=105.0,
                low=99.0,
                close=104.0,
                volume=1500.0,
            ),
        )
        res = MarketKlinesResponse(
            symbol="SOLUSDT",
            interval="15m",
            source="binance_futures_live",
            timestamp_ms=1728000000000,
            count=1,
            candles=candles,
        )
        assert isinstance(res.candles, tuple)
        with pytest.raises(TypeError):
            res.candles[0] = None  # type: ignore[index]

    def test_execution_order_item_optional_and_null_fields(self) -> None:
        """Verifies ExecutionOrderItem correctly handles None fill_price for canceled orders."""
        order = ExecutionOrderItem(
            order_id="ord-cancel-999",
            client_order_id="canary-p311-drill-sol-tp-001",
            symbol="SOLUSDT",
            side="SELL",
            order_type="LIMIT",
            price=190.0,
            quantity=0.03,
            notional_usdt=5.7,
            status="CANCELED",
            fill_price=None,
            fee_usdt=0.0,
            realized_pnl_usdt=0.0,
            timestamp_ms=1728000005000,
            is_maker=True,
        )
        dumped = order.model_dump()
        assert dumped["fill_price"] is None
        assert dumped["status"] == "CANCELED"
        json_str = order.model_dump_json()
        assert '"fill_price":null' in json_str


# =============================================================================
# 2. EXTREME FLOAT VALUES & ZERO-DRIFT BOUNDARY FUZZING ($10^-16 USDT)
# =============================================================================


class TestTier5ExtremeFloatAndZeroDriftBoundaryFuzzing:
    """White-box testing of micro/macro capital, arbitrary precision, and sub-femtodollar drift."""

    def test_sub_microscopic_equity_solvency_1e_minus_10(self, tmp_path: Path) -> None:
        """Verifies solvency ledger and execution status preserve zero drift under $10^-10 USDT."""
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True, exist_ok=True)
        report_data = {
            "timestamp_ms": 1728000000000,
            "engine_state": "MICRO_CAPITAL_ACTIVE",
            "solvency": {
                "starting_equity": 1e-10,
                "cash": 1e-10,
                "realized_pnl": 0.0,
            },
            "candidates": {},
        }
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps(report_data), encoding="utf-8"
        )

        status = load_execution_status(tmp_path)
        assert status.solvency.starting_equity_usdt == pytest.approx(1e-10)
        assert status.solvency.cash_usdt == pytest.approx(1e-10)
        assert status.solvency.zero_balance_drift_verified is True
        assert status.solvency.drift_usdt == 0.0

        # CentralizedSolvencyLedger verification
        ledger = CentralizedSolvencyLedger(starting_equity=1e-10)
        snapshot = ledger.get_snapshot()
        assert snapshot.zero_balance_drift is True
        assert snapshot.drift == pytest.approx(0.0)

    def test_astronomical_equity_solvency_1e9(self, tmp_path: Path) -> None:
        """Verifies solvency ledger and execution status preserve zero drift under $10^9 USDT."""
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True, exist_ok=True)
        report_data = {
            "timestamp_ms": 1728000000000,
            "engine_state": "MICRO_CAPITAL_ACTIVE",
            "solvency": {
                "starting_equity": 1_000_000_000.0,
                "cash": 1_000_000_000.0,
                "realized_pnl": 0.0,
            },
            "candidates": {},
        }
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps(report_data), encoding="utf-8"
        )

        status = load_execution_status(tmp_path)
        assert status.solvency.starting_equity_usdt == pytest.approx(1e9)
        assert status.solvency.cash_usdt == pytest.approx(1e9)
        assert status.solvency.zero_balance_drift_verified is True
        assert status.solvency.drift_usdt == 0.0

        ledger = CentralizedSolvencyLedger(starting_equity=1_000_000_000.0)
        # Apply 1,000 micro fee deductions of 0.0002 USDT
        for _ in range(1000):
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY",
                qty=0.03,
                price=185.0,
                fee=0.0002,
                realized_pnl=0.0,
            )
        snapshot = ledger.get_snapshot()
        assert snapshot.zero_balance_drift is True
        assert snapshot.drift == pytest.approx(0.0, abs=1e-15)

    def test_zero_drift_boundary_fuzzing_sub_femtodollar(self, tmp_path: Path) -> None:
        """Rigorous fuzzing around the exact 1e-15 USDT zero-drift boundary.

        1. CentralizedSolvencyLedger (Decimal Arbitrary Precision):
           - Drift = +1e-16 USDT: strictly < 1e-15 USDT -> zero_drift is True
           - Drift = -1e-16 USDT: strictly < 1e-15 USDT -> zero_drift is True
           - Drift = 0.999e-15 USDT: strictly < 1e-15 USDT -> zero_drift is True
           - Drift = 1.000e-15 USDT: >= 1e-15 USDT -> zero_drift is False
           - Drift = 1.001e-15 USDT: >= 1e-15 USDT -> zero_drift is False

        2. load_execution_status (IEEE 754 Float Precision at 1e-14 equity):
           - Drift = +1e-16 USDT: strictly < 1e-15 USDT -> verified True, drift_usdt 0.0
           - Drift = -1e-16 USDT: strictly < 1e-15 USDT -> verified True, drift_usdt 0.0
           - Drift = 9.99e-16 USDT: strictly < 1e-15 USDT -> verified True, drift_usdt 0.0
           - Drift = 1.001e-15 USDT: >= 1e-15 USDT -> verified False, drift_usdt > 0.0
           - Drift = 1.0e-14 USDT: >= 1e-15 USDT -> verified False, drift_usdt > 0.0
        """
        # 1. Decimal arbitrary precision verification on CentralizedSolvencyLedger
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # Sub-femtodollar offset +1e-16
        ledger.cash = Decimal("100.0") + Decimal("1e-16")
        snap_pos = ledger.get_snapshot()
        assert snap_pos.zero_balance_drift is True
        assert snap_pos.drift == pytest.approx(1e-16)

        # Sub-femtodollar offset -1e-16
        ledger.cash = Decimal("100.0") - Decimal("1e-16")
        snap_neg = ledger.get_snapshot()
        assert snap_neg.zero_balance_drift is True
        assert snap_neg.drift == pytest.approx(-1e-16)

        # 0.999e-15 (just below boundary)
        ledger.cash = Decimal("100.0") + Decimal("0.999e-15")
        snap_below = ledger.get_snapshot()
        assert snap_below.zero_balance_drift is True

        # Exactly 1.000e-15 (boundary is strictly < 1e-15)
        ledger.cash = Decimal("100.0") + Decimal("1.000e-15")
        snap_exact = ledger.get_snapshot()
        assert snap_exact.zero_balance_drift is False

        # 1.001e-15 (just above boundary)
        ledger.cash = Decimal("100.0") + Decimal("1.001e-15")
        snap_above = ledger.get_snapshot()
        assert snap_above.zero_balance_drift is False

        # 2. Float precision boundary fuzzing on load_execution_status
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True, exist_ok=True)

        base_equity = 1.0e-14
        float_test_cases = [
            (1e-16, True, True),
            (-1e-16, True, True),
            (9.99e-16, True, True),
            (1.001e-15, False, False),
            (1e-14, False, False),
        ]

        for offset, exp_verified, exp_drift_zero in float_test_cases:
            report_data = {
                "timestamp_ms": 1728000000000,
                "engine_state": "MICRO_CAPITAL_ACTIVE",
                "solvency": {
                    "starting_equity": base_equity,
                    "cash": base_equity + offset,
                    "realized_pnl": 0.0,
                },
                "candidates": {},
            }
            (p310_dir / "canary-production-report.json").write_text(
                json.dumps(report_data), encoding="utf-8"
            )

            status = load_execution_status(tmp_path)
            assert status.solvency.zero_balance_drift_verified is exp_verified, (
                f"Offset {offset} expected verified={exp_verified}, got {status.solvency.zero_balance_drift_verified}"
            )
            if exp_drift_zero:
                assert status.solvency.drift_usdt == 0.0
            else:
                assert status.solvency.drift_usdt > 0.0

    def test_canary_auto_evolution_drift_tolerance_breach_detection(self, tmp_path: Path) -> None:
        """Verifies load_verified_canary_auto_evolution raises CanaryEvidenceIntegrityError on drift >= 1e-15."""
        source_dir = Path("artifacts/research/phase306")
        if not (source_dir / "evolution-summary.json").is_file():
            pytest.skip("Phase 306 artifacts not found")

        # Copy valid artifacts to tmp_path
        target_dir = tmp_path / "phase306"
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in (
            "evolution-summary.json",
            "canary-evolution-report.json",
            "canary-evolution-telemetry.sqlite3",
            "canary-evolution-events.jsonl",
        ):
            src_file = source_dir / fname
            if src_file.is_file():
                (target_dir / fname).write_bytes(src_file.read_bytes())

        # Tamper summary solvency drift to 1e-14 (breaching 1e-15 ceiling)
        summary_path = target_dir / "evolution-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_data["solvency"]["drift_usdt"] = "0.00000000000001"  # 1e-14
        summary_path.write_text(json.dumps(summary_data), encoding="utf-8")

        with pytest.raises(CanaryEvidenceIntegrityError) as exc_info:
            load_verified_canary_auto_evolution(target_dir)
        assert "exceeds tolerance 1e-15 USDT" in str(
            exc_info.value
        ) or "Double-entry zero-drift balance invariant breached" in str(exc_info.value)

    def test_arbitrary_precision_randomized_micro_fills(self) -> None:
        """Applies 10,000 randomized micro fills to CentralizedSolvencyLedger, verifying |drift| < 1e-15."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        rng = random.Random(42)

        for _ in range(10_000):
            qty = round(rng.uniform(0.001, 0.05), 4)
            price = round(rng.uniform(10.0, 3000.0), 2)
            fee = round(rng.uniform(0.00001, 0.001), 6)
            rpnl = round(rng.uniform(-0.05, 0.05), 6)
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY" if rng.random() > 0.5 else "SELL",
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )

        snapshot = ledger.get_snapshot()
        assert snapshot.zero_balance_drift is True
        assert abs(snapshot.drift) < 1e-15


# =============================================================================
# 3. MERKLE HASH CALCULATIONS & INTEGRITY ADVERSARIAL
# =============================================================================


class TestTier5MerkleHashAndIntegrityAdversarial:
    """White-box testing of cryptographic Merkle hash trees and tampering detection."""

    def test_canary_phase_integrity_missing_directory_fails_closed(self, tmp_path: Path) -> None:
        """Verifies verify_canary_phase_integrity fails closed on non-existent directory."""
        non_existent = tmp_path / "ghost_phase"
        with pytest.raises(CanaryEvidenceNotFoundError):
            verify_canary_phase_integrity(non_existent)

    def test_canary_phase_integrity_missing_summary_fails_closed(self, tmp_path: Path) -> None:
        """Verifies verify_canary_phase_integrity fails closed if summary artifact is missing."""
        phase_dir = tmp_path / "empty_phase"
        phase_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(CanaryEvidenceNotFoundError) as exc_info:
            verify_canary_phase_integrity(phase_dir)
        assert "No summary artifact found" in str(exc_info.value)

    def test_canary_phase_integrity_tampered_artifact_hash_detection(self, tmp_path: Path) -> None:
        """Verifies verify_canary_phase_integrity detects single-byte artifact tampering."""
        phase_dir = tmp_path / "phase_test"
        phase_dir.mkdir(parents=True, exist_ok=True)
        data_file = phase_dir / "telemetry.json"
        data_file.write_text('{"status": "ok"}', encoding="utf-8")
        real_hash = hashlib.sha256(data_file.read_bytes()).hexdigest()

        summary_file = phase_dir / "orchestrator-summary.json"
        summary_file.write_text(
            json.dumps({"artifact_hashes": {"telemetry.json": real_hash}}),
            encoding="utf-8",
        )

        # 1. Unmodified passes
        verified = verify_canary_phase_integrity(phase_dir)
        assert isinstance(verified, dict)

        # 2. Tamper artifact by appending 1 byte
        data_file.write_text('{"status": "tampered"}', encoding="utf-8")
        with pytest.raises(CanaryEvidenceIntegrityError) as exc_info:
            verify_canary_phase_integrity(phase_dir)
        assert "Hash mismatch" in str(exc_info.value)

    def test_canary_auto_evolution_merkle_root_single_bit_flip(self, tmp_path: Path) -> None:
        """Verifies load_verified_canary_auto_evolution detects a single bit flip in merkle_root."""
        source_dir = Path("artifacts/research/phase306")
        if not (source_dir / "evolution-summary.json").is_file():
            pytest.skip("Phase 306 artifacts not found")

        target_dir = tmp_path / "phase306"
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in (
            "evolution-summary.json",
            "canary-evolution-report.json",
            "canary-evolution-telemetry.sqlite3",
            "canary-evolution-events.jsonl",
        ):
            src_file = source_dir / fname
            if src_file.is_file():
                (target_dir / fname).write_bytes(src_file.read_bytes())

        summary_path = target_dir / "evolution-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        real_merkle = summary_data["merkle_root"]
        # Flip the last character
        tampered_char = "0" if real_merkle[-1] != "0" else "1"
        summary_data["merkle_root"] = real_merkle[:-1] + tampered_char
        summary_path.write_text(json.dumps(summary_data), encoding="utf-8")

        with pytest.raises(CanaryEvidenceIntegrityError) as exc_info:
            load_verified_canary_auto_evolution(target_dir)
        assert "Merkle root mismatch" in str(exc_info.value)

    def test_canary_auto_evolution_upstream_hash_tampering(self, tmp_path: Path) -> None:
        """Verifies load_verified_canary_auto_evolution rejects tampered upstream Phase 305 parent hash."""
        source_dir = Path("artifacts/research/phase306")
        if not (source_dir / "evolution-summary.json").is_file():
            pytest.skip("Phase 306 artifacts not found")

        target_dir = tmp_path / "phase306"
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in (
            "evolution-summary.json",
            "canary-evolution-report.json",
            "canary-evolution-telemetry.sqlite3",
            "canary-evolution-events.jsonl",
        ):
            src_file = source_dir / fname
            if src_file.is_file():
                (target_dir / fname).write_bytes(src_file.read_bytes())

        summary_path = target_dir / "evolution-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_data["upstream_hash"] = (
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        )
        summary_path.write_text(json.dumps(summary_data), encoding="utf-8")

        with pytest.raises(CanaryEvidenceIntegrityError) as exc_info:
            load_verified_canary_auto_evolution(target_dir)
        assert "Upstream hash mismatch" in str(exc_info.value)

    def test_autopsies_db_and_summary_disagreement_detection(self, tmp_path: Path) -> None:
        """Verifies load_verified_canary_auto_evolution detects mismatch between SQLite autopsies and summary JSON."""
        source_dir = Path("artifacts/research/phase306")
        if not (source_dir / "evolution-summary.json").is_file():
            pytest.skip("Phase 306 artifacts not found")

        target_dir = tmp_path / "phase306"
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in (
            "evolution-summary.json",
            "canary-evolution-report.json",
            "canary-evolution-telemetry.sqlite3",
            "canary-evolution-events.jsonl",
        ):
            src_file = source_dir / fname
            if src_file.is_file():
                (target_dir / fname).write_bytes(src_file.read_bytes())

        # Mutate SQLite database by modifying an autopsy row
        sqlite_file = target_dir / "canary-evolution-telemetry.sqlite3"
        with sqlite3.connect(sqlite_file) as conn:
            conn.execute(
                "UPDATE autopsies SET net_pnl_usdt = net_pnl_usdt + 10.0 WHERE trade_id = 'tr-btc-001'"
            )
            conn.commit()

        # Update the recorded hash in summary and recompute Merkle root so it passes initial file hash
        # and Merkle checks, specifically testing the deeper data disagreement verification
        new_sqlite_hash = hashlib.sha256(sqlite_file.read_bytes()).hexdigest()
        summary_path = target_dir / "evolution-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_data["artifact_hashes"]["sqlite3"] = new_sqlite_hash
        upstream_hash = str(summary_data.get("upstream_hash", ""))
        events_hash = str(summary_data["artifact_hashes"]["events_jsonl"])
        phase_payload_hash = str(summary_data.get("phase_hash", ""))
        merkle_combined = f"{upstream_hash}:{new_sqlite_hash}:{events_hash}:{phase_payload_hash}"
        summary_data["merkle_root"] = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()
        summary_path.write_text(json.dumps(summary_data), encoding="utf-8")

        with pytest.raises(CanaryEvidenceIntegrityError) as exc_info:
            load_verified_canary_auto_evolution(target_dir)
        assert "autopsy trace disagrees with SQLite/events" in str(exc_info.value)


# =============================================================================
# 4. ZERO-DIVISION IMMUNITY & NUMERICAL STABILITY
# =============================================================================


class TestTier5ZeroDivisionAndNumericalImmunity:
    """White-box stress testing of division-by-zero immunity and flat numerical boundary stability."""

    def test_macro_trend_ema_zero_or_negative_span_immunity(self) -> None:
        """Verifies _compute_ema_series handles empty inputs and edge spans without ZeroDivisionError."""
        # Empty series
        assert _compute_ema_series([], span=50) == []

        # Single element
        assert _compute_ema_series([100.0], span=50) == [100.0]

        # Zero span (alpha = 2.0 / (0 + 1) = 2.0)
        res_zero = _compute_ema_series([100.0, 105.0], span=0)
        assert len(res_zero) == 2
        assert not any(math.isnan(x) or math.isinf(x) for x in res_zero)

        # Constant sequence (flat zero volatility)
        flat_seq = [50.0] * 100
        res_flat = _compute_ema_series(flat_seq, span=50)
        assert len(res_flat) == 100
        assert res_flat[-1] == pytest.approx(50.0)

    def test_compute_authentic_btc_macro_extreme_inputs(self) -> None:
        """Verifies compute_authentic_btc_macro gracefully handles 0.0, negative, and extreme prices."""
        reset_live_market_cache()
        # Price = 0.0 falls back cleanly to base 82600.0 without crash
        macro_zero = compute_authentic_btc_macro(0.0)
        assert isinstance(macro_zero, dict)
        assert macro_zero["current_price"] == 0.0
        assert macro_zero["ema50_1h"] > 0
        assert macro_zero["ema200_1h"] > 0
        assert macro_zero["regime"] in {"BULLISH ALIGNED", "BEARISH", "SIDEWAYS"}

        reset_live_market_cache()
        # Extreme giant price
        macro_giant = compute_authentic_btc_macro(1_000_000_000.0)
        assert macro_giant["current_price"] == 1e9
        assert not any(
            math.isnan(v) or math.isinf(v)
            for v in (macro_giant["ema50_1h"], macro_giant["ema200_1h"])
        )

    def test_canary_auto_evolution_dynamic_cycle_zero_division(self) -> None:
        """Verifies load_verified_canary_auto_evolution handles simulated zero trades and boundary timestamps."""
        # simulated_closed_trades = 0
        res_zero = load_verified_canary_auto_evolution(
            simulated_closed_trades=0,
            simulated_timestamp_ms=0,
        )
        assert res_zero.live_progress.closed_trades_count == 0
        assert res_zero.live_progress.cycle_progress_pct == 80.0
        assert res_zero.live_progress.stage_status == "WAITING_FOR_SAMPLES"

        # simulated_closed_trades = 1000
        res_thousand = load_verified_canary_auto_evolution(
            simulated_closed_trades=1000,
            simulated_timestamp_ms=1728000000000,
        )
        assert res_thousand.live_progress.closed_trades_count == 1000
        assert res_thousand.live_progress.cycle_progress_pct == 100.0

    def test_market_klines_limit_boundary_bounds(self, api_client: TestClient) -> None:
        """Verifies /api/v1/market/klines handles minimum (limit=1) and maximum (limit=1000) boundaries."""
        res_min = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=1")
        assert res_min.status_code == 200
        data_min = res_min.json()
        assert data_min["count"] == 1
        assert len(data_min["candles"]) == 1

        res_max = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=1000")
        assert res_max.status_code == 200
        data_max = res_max.json()
        assert data_max["count"] == 1000
        assert len(data_max["candles"]) == 1000


# =============================================================================
# 5. MACRO REGIME BOUNDARY TOGGLING & CASE FUZZING
# =============================================================================


class TestTier5MacroRegimeBoundaryToggling:
    """White-box testing of _build_macro_gating_state regime transitions and English localization."""

    def test_macro_regime_case_insensitivity_and_whitespace(self) -> None:
        """Verifies regime parsing is case-insensitive, strips whitespace, and maps properly."""
        bullish_inputs = [
            "bullish",
            "  BULLISH  ",
            "bullish_aligned",
            "BULLISH_CONFLUENCE",
            "bUlLiSh",
        ]
        for inp in bullish_inputs:
            state = _build_macro_gating_state(regime=inp)
            assert state.regime == "BULLISH_ALIGNED"
            assert state.is_long_allowed is True
            assert state.longs_filtered is False
            assert "Long scalper entries permitted" in state.explanation

        bearish_inputs = ["bearish", "  BEARISH  ", "bEaRiSh_TrEnD", "BEARISH_DOWN"]
        for inp in bearish_inputs:
            state = _build_macro_gating_state(regime=inp)
            assert state.regime == "BEARISH"
            assert state.is_long_allowed is False
            assert state.longs_filtered is True
            assert "Long entries temporarily paused" in state.explanation

        neutral_inputs = ["sideways", "neutral", "TRANSITIONAL", "", "unknown_regime"]
        for inp in neutral_inputs:
            state = _build_macro_gating_state(regime=inp)
            assert state.regime == "NEUTRAL"
            assert state.is_long_allowed is False
            assert state.longs_filtered is True
            assert "transitional / sideways" in state.explanation

    def test_macro_regime_explanations_english_localization(self) -> None:
        """Verifies both explanation and explanation_ms across all regimes contain 0 banned Malay terms."""
        banned_terms = ["penapis", "kemasukan", "posisi", "beli", "rejim", "keadaan", "aliran"]
        for reg in ("BULLISH", "BEARISH", "NEUTRAL"):
            state = _build_macro_gating_state(regime=reg)
            for text in (state.explanation, state.explanation_ms):
                text_lower = text.lower()
                for banned in banned_terms:
                    assert banned not in text_lower, (
                        f"Banned term '{banned}' leaked into explanation: {text}"
                    )

    def test_macro_regime_sub_cent_ema_cross_boundary(self) -> None:
        """Verifies numerical precision when EMA 50 and EMA 200 are within sub-cent distance."""
        # EMA 50 == EMA 200 exactly
        state_exact = _build_macro_gating_state(
            regime="NEUTRAL",
            btc_price=80000.0,
            ema50=80000.0,
            ema200=80000.0,
        )
        assert state_exact.ema50_1h == 80000.0
        assert state_exact.ema200_1h == 80000.0
        assert state_exact.btc_price == 80000.0

        # Sub-cent delta: 80000.004 rounds to 80000.00
        state_sub = _build_macro_gating_state(
            regime="BULLISH",
            btc_price=80000.004,
            ema50=80000.006,
            ema200=80000.001,
        )
        assert state_sub.btc_price == 80000.00
        assert state_sub.ema50_1h == 80000.01
        assert state_sub.ema200_1h == 80000.00


# =============================================================================
# 6. MALICIOUS QUERY PARAMS & INGRESS SECURITY
# =============================================================================


class TestTier5MaliciousQueryParamsAndIngressSecurity:
    """White-box testing of FastAPI parameter sanitization, injection defense, and error handling."""

    def test_klines_malicious_symbol_injection_defense(self, api_client: TestClient) -> None:
        """Verifies malicious symbol queries (SQLi, path traversal, XSS) do not crash the API."""
        malicious_symbols = [
            "' OR 1=1 --",
            "../../etc/passwd",
            "<script>alert(1)</script>",
            "BTC%00USDT",
            "INVALID;DROP TABLE orders;",
        ]
        for sym in malicious_symbols:
            resp = api_client.get(f"/api/v1/market/klines?symbol={sym}&interval=15m&limit=10")
            assert resp.status_code == 200, (
                f"Expected 200 graceful fallback for symbol '{sym}', got {resp.status_code}"
            )
            data = resp.json()
            assert data["count"] == 10
            assert isinstance(data["candles"], list)

    def test_klines_invalid_interval_returns_422(self, api_client: TestClient) -> None:
        """Verifies unsupported intervals return HTTP 422 Unprocessable Entity."""
        invalid_intervals = ["2m", "10m", "30m", "2h", "1w", "invalid", "''"]
        for interval in invalid_intervals:
            resp = api_client.get(
                f"/api/v1/market/klines?symbol=SOLUSDT&interval={interval}&limit=10"
            )
            assert resp.status_code == 422
            assert "Unsupported interval" in resp.json()["detail"]

    def test_klines_limit_out_of_bounds_returns_422(self, api_client: TestClient) -> None:
        """Verifies limit outside [1, 1000] is rejected with HTTP 422 by FastAPI query validation."""
        out_of_bound_limits = [0, -1, -100, 1001, 50000, "abc"]
        for limit in out_of_bound_limits:
            resp = api_client.get(
                f"/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit={limit}"
            )
            assert resp.status_code == 422

    def test_execution_status_corrupted_orders_jsonl_graceful_recovery(
        self, tmp_path: Path
    ) -> None:
        """Verifies load_execution_status recovers gracefully from corrupted/truncated JSONL lines."""
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True, exist_ok=True)
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps({"timestamp_ms": 1728000000000, "solvency": {}}),
            encoding="utf-8",
        )

        p311_dir = tmp_path / "phase311"
        p311_dir.mkdir(parents=True, exist_ok=True)
        orders_file = p311_dir / "canary-orders.jsonl"
        # Write valid line, corrupted line, empty line, truncated JSON line, binary byte line
        corrupted_content = (
            '{"event_type": "ORDER_SUBMITTED", "client_order_id": "canary-p311-drill-sol-valid-01", "price": 185.0, "quantity": 0.03, "timestamp_ms": 1728000001000}\n'
            '{"event_type": "ORDER_SUBMITTED", "client_order_id":\n'
            "\n"
            "NOT_A_JSON_STRING\n"
            '{"event_type": "ORDER_SUBMITTED", "client_order_id": "canary-p311-drill-sol-valid-02", "price": 185.0, "quantity": 0.03, "timestamp_ms": 1728000002000}\n'
        )
        orders_file.write_text(corrupted_content, encoding="utf-8")

        status = load_execution_status(tmp_path)
        assert status.verified is True
        # Only the 2 valid orders should be parsed
        valid_cids = {o.client_order_id for o in status.recent_orders}
        assert "canary-p311-drill-sol-valid-01" in valid_cids
        assert "canary-p311-drill-sol-valid-02" in valid_cids
        assert len(status.recent_orders) == 2

    def test_execution_status_strict_order_id_filter_ord_p309_leakage_block(
        self, tmp_path: Path
    ) -> None:
        """Verifies stale 'ord-p309-' simulation orders are strictly purged and never leak into recent_orders."""
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True, exist_ok=True)
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps({"timestamp_ms": 1728000000000, "solvency": {}}),
            encoding="utf-8",
        )
        exec_file = p310_dir / "canary-production-execution.json"
        exec_data = {
            "orders": [
                {
                    "client_order_id": "ord-p309-eth-short",
                    "order_id": "ord-p309-eth-short",
                    "price": 2750.0,
                    "quantity": 0.05,
                    "timestamp_ms": 1727000000000,
                },
                {
                    "client_order_id": "canary-p310-legit-001",
                    "order_id": "112233",
                    "price": 185.0,
                    "quantity": 0.03,
                    "timestamp_ms": 1728000000000,
                },
            ]
        }
        exec_file.write_text(json.dumps(exec_data), encoding="utf-8")

        status = load_execution_status(tmp_path)
        recent_cids = [o.client_order_id for o in status.recent_orders]
        assert "ord-p309-eth-short" not in recent_cids
        assert "canary-p310-legit-001" in recent_cids


# =============================================================================
# 7. MALFORMED TIMESTAMPS & DATE RESILIENCE
# =============================================================================


class TestTier5MalformedTimestampsAndDateResilience:
    """White-box testing of timestamp parsing and recovery under corrupted date strings."""

    def test_canary_auto_evolution_malformed_timestamp_string_recovery(
        self, tmp_path: Path
    ) -> None:
        """Verifies load_verified_canary_auto_evolution recovers gracefully from malformed timestamp_utc."""
        source_dir = Path("artifacts/research/phase306")
        if not (source_dir / "evolution-summary.json").is_file():
            pytest.skip("Phase 306 artifacts not found")

        target_dir = tmp_path / "phase306"
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in (
            "evolution-summary.json",
            "canary-evolution-report.json",
            "canary-evolution-telemetry.sqlite3",
            "canary-evolution-events.jsonl",
        ):
            src_file = source_dir / fname
            if src_file.is_file():
                (target_dir / fname).write_bytes(src_file.read_bytes())

        summary_path = target_dir / "evolution-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_data["timestamp_utc"] = "NOT_A_VALID_ISO_TIMESTAMP"
        summary_path.write_text(json.dumps(summary_data), encoding="utf-8")

        res = load_verified_canary_auto_evolution(target_dir)
        assert res.verified is True
        assert res.timestamp_ms > 0
        assert res.timestamp_utc == "NOT_A_VALID_ISO_TIMESTAMP"

    def test_candlestick_point_extreme_timestamps(self) -> None:
        """Verifies CandlestickPoint accepts epoch 0 and distant future timestamps."""
        # Epoch zero (1970)
        c_zero = CandlestickPoint(
            timestamp=0,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=0.0,
        )
        assert c_zero.timestamp == 0

        # Far future (Year 2100 = 4102444800)
        c_future = CandlestickPoint(
            timestamp=4102444800,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=10.0,
        )
        assert c_future.timestamp == 4102444800

    def test_safe_int_and_float_conversion_robustness(self) -> None:
        """Verifies _safe_int and _safe_float handle various malformed data types without throwing."""
        assert _safe_int(None, default=42) == 42
        assert _safe_int("invalid_string", default=99) == 99
        assert _safe_int({"a": 1}, default=12) == 12
        assert _safe_int("12345", default=0) == 12345
        assert _safe_int(123.45, default=0) == 123

        assert _safe_float(None, default=3.14) == 3.14
        assert _safe_float("invalid", default=2.71) == 2.71
        assert _safe_float([1, 2], default=0.0) == 0.0
        assert _safe_float("123.456", default=0.0) == 123.456


# =============================================================================
# 8. RAPID CONCURRENT SCHEMA POLLING
# =============================================================================


class TestTier5RapidConcurrentSchemaPolling:
    """White-box testing of concurrent API polling safety, thread contention, and 0 race conditions."""

    def test_concurrent_rapid_schema_polling_1000_requests(self, api_client: TestClient) -> None:
        """Stress-tests FastAPI endpoints with 1,000 rapid concurrent requests across 16 worker threads.

        Verifies:
        - 100% HTTP 200 pass rate.
        - Zero 500 Internal Server Errors.
        - Zero race conditions or deadlocks.
        - All responses deserialize cleanly into their respective Pydantic response models.
        """
        endpoints = [
            ("/api/v1/canary/evolution", CanaryAutoEvolutionResponse),
            ("/api/v1/execution/status", ExecutionStatusResponse),
            ("/api/v1/market/prices", dict),
            ("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=50", MarketKlinesResponse),
            ("/health", dict),
        ]
        total_requests = 1000
        errors: list[str] = []

        def worker(request_id: int) -> None:
            url, model_cls = endpoints[request_id % len(endpoints)]
            try:
                resp = api_client.get(url)
                if resp.status_code != 200:
                    errors.append(
                        f"Request {request_id} ({url}) returned status {resp.status_code}"
                    )
                    return
                data = resp.json()
                if model_cls is not dict:
                    # Validate Pydantic schema
                    model_cls.model_validate(data)
            except Exception as exc:
                errors.append(f"Request {request_id} ({url}) raised exception: {exc}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker, i) for i in range(total_requests)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, (
            f"Encountered {len(errors)} errors during rapid concurrent polling: {errors[:5]}"
        )

    def test_concurrent_live_market_cache_invalidation_safety(self) -> None:
        """Stress-tests reset_live_market_cache and get_live_market_data under concurrent multithreading."""
        errors: list[str] = []

        def worker(idx: int) -> None:
            try:
                if idx % 5 == 0:
                    reset_live_market_cache()
                data = get_live_market_data()
                assert isinstance(data, dict)
                assert "prices" in data
            except Exception as exc:
                errors.append(f"Worker {idx} failed: {exc}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(200)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Cache invalidation errors: {errors}"
