"""Empirical Challenger Test Suite for Milestone 1 / Phase 314.

Challenger instance: challenger_m1_2
Target: Backend order feeds, position states, data serialization, and zero-drift balance invariant.

Empirical verification covers:
1. Default application /api/v1/execution/status endpoint:
   - Zero occurrences of 'ord-p309-' in orders, client order IDs, or payload JSON.
   - 100% authentic order IDs starting with 'canary-p310-' or 'canary-p311-'.
   - Candidate positions (BTCUSDT, ETHUSDT, SOLUSDT) have position_qty == 0.0,
     allocated_exposure_usdt == 0.0, and state == 'STANDBY / SCANNING'.
   - Double-entry balance drift is strictly 0.0 (|Delta| < 10^-15).
2. Adversarial stress & fuzzing:
   - Poisoned orders injection (ord-p309- tampering, spoofed order_id, malformed prefixes).
   - Solvency drift oracle verification (|Delta| thresholding).
   - Schema serialization, Pydantic roundtrip, and absence of NaN / Infinity.
   - Corrupted and missing research artifact fault injection.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.api.app import (
    ExecutionStatusResponse,
    load_execution_status,
    reset_live_market_cache,
)


def _request_sync(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def _send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(_send())


class TestEmpiricalExecutionStatusDefaultApp:
    """Empirical challenge on the live default application state."""

    @pytest.fixture(autouse=True)
    def setup_app(self) -> None:
        reset_live_market_cache()
        self.app = create_app()

    def test_no_ord_p309_in_execution_status(self) -> None:
        """Asserts that NO order ID contains 'ord-p309-' anywhere in the payload."""
        response = _request_sync(self.app, "GET", "/api/v1/execution/status")
        assert response.status_code == 200, f"Unexpected status: {response.status_code}"
        payload = response.json()

        # 1. Payload raw string check
        payload_str = json.dumps(payload)
        assert "ord-p309-" not in payload_str, (
            "Forbidden pattern 'ord-p309-' leaked into serialized execution status payload!"
        )

        # 2. Granular order items check
        recent_orders = payload.get("recent_orders", [])
        assert len(recent_orders) > 0, "Expected non-empty authentic orders list"

        for idx, order in enumerate(recent_orders):
            cid = order.get("client_order_id", "")
            oid = str(order.get("order_id", ""))
            assert "ord-p309-" not in cid, (
                f"Order #{idx} client_order_id contains ord-p309-: {cid}"
            )
            assert "ord-p309-" not in oid, (
                f"Order #{idx} order_id contains ord-p309-: {oid}"
            )
            assert not cid.startswith("ord-p309-"), (
                f"Order #{idx} cid starts with ord-p309-: {cid}"
            )
            assert not oid.startswith("ord-p309-"), (
                f"Order #{idx} oid starts with ord-p309-: {oid}"
            )

    def test_all_orders_match_authentic_canary_prefixes(self) -> None:
        """Asserts that ALL recent order IDs match authentic canary prefixes."""
        response = _request_sync(self.app, "GET", "/api/v1/execution/status")
        assert response.status_code == 200
        payload = response.json()

        recent_orders = payload.get("recent_orders", [])
        assert len(recent_orders) > 0, "recent_orders should contain authentic orders"

        p310_count = 0
        p311_count = 0

        for idx, order in enumerate(recent_orders):
            cid = order.get("client_order_id", "")
            assert cid, f"Order #{idx} is missing client_order_id"

            is_p310 = cid.startswith("canary-p310-")
            is_p311 = cid.startswith("canary-p311-")
            assert is_p310 or is_p311, (
                f"Order #{idx} client_order_id '{cid}' violates authentic prefix contract! "
                "Must start with 'canary-p310-' or 'canary-p311-'."
            )

            if is_p310:
                p310_count += 1
            if is_p311:
                p311_count += 1

            # Validate mandatory order attributes
            assert order.get("symbol") in {"SOLUSDT", "ETHUSDT", "BTCUSDT"}
            assert order.get("side") in {"BUY", "SELL"}
            assert order.get("status") in {"FILLED", "CANCELED", "NEW"}
            assert isinstance(order.get("price"), (int, float))
            assert order.get("price") >= 0.0
            assert isinstance(order.get("quantity"), (int, float))
            assert order.get("quantity") >= 0.0
            assert isinstance(order.get("notional_usdt"), (int, float))
            assert order.get("notional_usdt") >= 0.0
            assert isinstance(order.get("fee_usdt"), (int, float))
            assert order.get("fee_usdt") >= 0.0
            assert isinstance(order.get("timestamp_ms"), int)
            assert order.get("timestamp_ms") > 0

        # Confirm representation from both active phases
        assert p310_count > 0, f"Expected Phase 310 orders in feed, found {p310_count}"
        assert p311_count > 0, f"Expected Phase 311 orders in feed, found {p311_count}"
        assert p310_count + p311_count == len(recent_orders)

        # Confirm strict descending chronological ordering
        timestamps = [o["timestamp_ms"] for o in recent_orders]
        assert timestamps == sorted(timestamps, reverse=True), (
            "Recent orders are not sorted in descending chronological order!"
        )

    def test_candidate_positions_strictly_standby_and_zero_exposure(self) -> None:
        """Asserts candidate positions have zero exposure and standby state."""
        response = _request_sync(self.app, "GET", "/api/v1/execution/status")
        assert response.status_code == 200
        payload = response.json()

        assert payload.get("aggregate_exposure_usdt") == 0.0, (
            f"Expected aggregate_exposure_usdt == 0.0, got {payload.get('aggregate_exposure_usdt')}"
        )

        positions = payload.get("positions", {})
        expected_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        assert set(positions.keys()) == expected_symbols, (
            f"Positions keys {set(positions.keys())} do not match expected {expected_symbols}"
        )

        for sym in expected_symbols:
            pos = positions[sym]
            assert pos.get("symbol") == sym
            assert pos.get("position_qty") == 0.0, (
                f"{sym} has non-zero position_qty: {pos.get('position_qty')}"
            )
            assert pos.get("allocated_exposure_usdt") == 0.0, (
                f"{sym} has non-zero allocated_exposure_usdt: {pos.get('allocated_exposure_usdt')}"
            )
            assert pos.get("allocated_margin_usdt") == 0.0, (
                f"{sym} has non-zero allocated_margin_usdt: {pos.get('allocated_margin_usdt')}"
            )
            assert pos.get("unrealized_pnl_usdt") == 0.0, (
                f"{sym} has non-zero unrealized_pnl_usdt: {pos.get('unrealized_pnl_usdt')}"
            )
            assert pos.get("state") == "STANDBY / SCANNING", (
                f"{sym} state is '{pos.get('state')}', expected 'STANDBY / SCANNING'"
            )
            assert pos.get("status") == "STANDBY / SCANNING", (
                f"{sym} status is '{pos.get('status')}', expected 'STANDBY / SCANNING'"
            )
            assert pos.get("entry_price") is None, (
                f"{sym} has phantom entry_price: {pos.get('entry_price')}"
            )
            assert pos.get("take_profit_price") is None, (
                f"{sym} has phantom take_profit_price: {pos.get('take_profit_price')}"
            )
            assert pos.get("stop_loss_price") is None, (
                f"{sym} has phantom stop_loss_price: {pos.get('stop_loss_price')}"
            )

            # Mark price must be positive and dynamic
            mark_p = pos.get("mark_price")
            assert isinstance(mark_p, (int, float)) and mark_p > 0.0, (
                f"{sym} invalid mark_price: {mark_p}"
            )
            if sym == "BTCUSDT":
                # Ensure the stale 95,000 backtest placeholder is never served
                assert mark_p != 95000.0, (
                    "BTCUSDT mark price is stuck at stale 95000.0 placeholder!"
                )

        # Candidate allocations list check
        allocations = payload.get("candidate_allocations", [])
        assert len(allocations) == 3
        alloc_symbols = {a.get("symbol") for a in allocations}
        assert alloc_symbols == expected_symbols
        for a in allocations:
            assert a.get("position_qty") == 0.0
            assert a.get("allocated_exposure_usdt") == 0.0
            assert a.get("state") == "STANDBY / SCANNING"

    def test_double_entry_balance_drift_strictly_zero(self) -> None:
        """Asserts double-entry balance drift is strictly 0.0 (|Delta| < 10^-15)."""
        response = _request_sync(self.app, "GET", "/api/v1/execution/status")
        assert response.status_code == 200
        payload = response.json()

        solvency = payload.get("solvency", {})
        assert solvency, "Missing solvency object in payload"

        cash = solvency.get("cash_usdt")
        margin = solvency.get("allocated_margin_usdt")
        unrealized_pnl = solvency.get("unrealized_pnl_usdt")
        starting_equity = solvency.get("starting_equity_usdt")
        realized_pnl = solvency.get("realized_pnl_usdt")
        drift = solvency.get("drift_usdt")
        verified = solvency.get("zero_balance_drift_verified")
        cash_reserve_pct = solvency.get("cash_reserve_pct")
        unencumbered_cash_verified = solvency.get("unencumbered_cash_verified")

        assert isinstance(cash, (int, float))
        assert isinstance(margin, (int, float))
        assert isinstance(unrealized_pnl, (int, float))
        assert isinstance(starting_equity, (int, float))
        assert isinstance(realized_pnl, (int, float))

        # Balance Equation:
        # Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL
        lhs = cash + margin + unrealized_pnl
        rhs = starting_equity + realized_pnl
        delta = abs(lhs - rhs)

        assert delta < 1e-15, f"Mathematical balance drift violation: |Delta| = {delta} >= 1e-15"
        assert drift == 0.0 or abs(drift) < 1e-15, f"Reported drift_usdt non-zero: {drift}"
        assert verified is True, "zero_balance_drift_verified is False!"
        assert cash_reserve_pct == 100.0, f"Expected 100.0 cash reserve pct, got {cash_reserve_pct}"
        assert unencumbered_cash_verified is True, "unencumbered_cash_verified is False!"


class TestAdversarialStressAndOracles:
    """Adversarial stress-testing of backend order feeds and solvency oracles."""

    def test_poisoned_order_feed_quarantine(self, tmp_path: Path) -> None:
        """Adversarial scenario: Ingress files containing hostile ord-p309- records are rejected."""
        p310_dir = tmp_path / "phase310"
        p311_dir = tmp_path / "phase311"
        p310_dir.mkdir(parents=True)
        p311_dir.mkdir(parents=True)

        # 1. Hostile phase310 execution file containing authentic and poisoned orders
        poisoned_p310_exec = {
            "phase": "phase_310",
            "timestamp_ms": 1791511262886,
            "orders": [
                # Legitimate authentic order
                {
                    "order_id": "ord-p310-sol-0001",
                    "client_order_id": "canary-p310-sol-1790250000000-0e963a",
                    "symbol": "SOLUSDT",
                    "side": "BUY",
                    "price": 171.0,
                    "quantity": 0.03,
                    "status": "FILLED",
                    "timestamp_ms": 1790250000000,
                },
                # Poisoned: starts with ord-p309-
                {
                    "order_id": "ord-p309-sol-evil",
                    "client_order_id": "ord-p309-sol-evil-client",
                    "symbol": "SOLUSDT",
                    "side": "BUY",
                    "price": 171.0,
                    "quantity": 0.03,
                    "status": "FILLED",
                    "timestamp_ms": 1790250000100,
                },
                # Poisoned: authentic client_order_id prefix but order_id is ord-p309-
                {
                    "order_id": "ord-p309-trojan",
                    "client_order_id": "canary-p310-sol-trojan-1234",
                    "symbol": "SOLUSDT",
                    "side": "SELL",
                    "price": 175.0,
                    "quantity": 0.03,
                    "status": "FILLED",
                    "timestamp_ms": 1790250000200,
                },
                # Poisoned: random unknown prefix
                {
                    "order_id": "999999",
                    "client_order_id": "attacker-exploit-order-999",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "price": 50000.0,
                    "quantity": 1.0,
                    "status": "FILLED",
                    "timestamp_ms": 1790250000300,
                },
            ],
        }
        (p310_dir / "canary-production-execution.json").write_text(
            json.dumps(poisoned_p310_exec), encoding="utf-8"
        )

        # 2. Hostile phase311 orders JSONL with ord-p309- events
        jsonl_lines = [
            json.dumps({
                "timestamp_ms": 1791552527222,
                "event_type": "ORDER_SUBMITTED",
                "order_id": "82745773",
                "client_order_id": "canary-p311-drill-sol-1791552527210",
                "status": "NEW",
            }),
            json.dumps({
                "timestamp_ms": 1791552527299,
                "event_type": "ORDER_SUBMITTED",
                "order_id": "ord-p309-stream-poison",
                "client_order_id": "ord-p309-stream-poison-cid",
                "status": "NEW",
            }),
        ]
        (p311_dir / "canary-orders.jsonl").write_text(
            "\n".join(jsonl_lines), encoding="utf-8"
        )

        # Valid baseline reports for solvency
        p310_report = {
            "timestamp_ms": 1791511262886,
            "solvency": {
                "starting_equity": 100.0,
                "cash": 100.0,
                "realized_pnl": 0.0,
            },
            "candidates": {
                "BTCUSDT": {"current_price": 82600.0},
                "ETHUSDT": {"current_price": 2500.0},
                "SOLUSDT": {"current_price": 110.0},
            },
        }
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps(p310_report), encoding="utf-8"
        )

        status_resp = load_execution_status(tmp_path)
        orders = status_resp.recent_orders

        # Assert: Exactly the 2 legitimate orders survived; ALL poisoned records quarantined
        surviving_cids = [o.client_order_id for o in orders]
        assert "canary-p310-sol-1790250000000-0e963a" in surviving_cids
        assert "canary-p311-drill-sol-1791552527210" in surviving_cids

        # Assert zero leakage
        for o in orders:
            assert "ord-p309-" not in o.client_order_id
            assert "ord-p309-" not in o.order_id
            assert not o.client_order_id.startswith("ord-p309-")
            assert not o.order_id.startswith("ord-p309-")
            valid_prefix = (
                o.client_order_id.startswith("canary-p310-")
                or o.client_order_id.startswith("canary-p311-")
            )
            assert valid_prefix

        assert len(orders) == 2, f"Expected exactly 2 legitimate orders, got {len(orders)}"

    def test_solvency_drift_oracle_detects_nonzero_drift(self, tmp_path: Path) -> None:
        """Adversarial scenario: Artificial balance discrepancy must fail verification."""
        p310_dir = tmp_path / "phase310"
        p310_dir.mkdir(parents=True)

        # Deliberately unbalanced solvency: cash = 95.0, start = 100.0, realized = 0.0 (drift = 5.0)
        unbalanced_report = {
            "timestamp_ms": 1791511262886,
            "solvency": {
                "starting_equity": 100.0,
                "cash": 95.0,
                "realized_pnl": 0.0,
            },
        }
        (p310_dir / "canary-production-report.json").write_text(
            json.dumps(unbalanced_report), encoding="utf-8"
        )

        status_resp = load_execution_status(tmp_path)
        solvency = status_resp.solvency

        assert solvency.zero_balance_drift_verified is False
        assert solvency.drift_usdt == 5.0

    def test_serialization_pydantic_roundtrip_and_no_nan_inf(self) -> None:
        """Fuzzes serialization of execution status payload to ensure valid schema integrity."""
        reset_live_market_cache()
        app = create_app()
        response = _request_sync(app, "GET", "/api/v1/execution/status")
        assert response.status_code == 200
        payload = response.json()

        # Check content-type header
        assert "application/json" in response.headers.get("content-type", "")

        # Pydantic schema validation
        validated = ExecutionStatusResponse.model_validate(payload)
        assert validated.verified is True
        assert validated.aggregate_exposure_usdt == 0.0
        assert validated.solvency.zero_balance_drift_verified is True

        # Deep search for NaN / Infinity
        def _check_numbers(obj: Any, path: str = "root") -> None:
            if isinstance(obj, float):
                assert not math.isnan(obj), f"NaN float found at {path}"
                assert not math.isinf(obj), f"Infinity float found at {path}"
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    _check_numbers(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _check_numbers(v, f"{path}[{i}]")

        _check_numbers(payload)

        # JSON roundtrip
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded == payload

    def test_fault_injection_corrupt_or_empty_research_dir_fails_gracefully(
        self, tmp_path: Path
    ) -> None:
        """Fault injection: Missing, corrupt JSON, or empty directory falls back to baseline."""
        corrupt_dir = tmp_path / "corrupt"
        corrupt_p310 = corrupt_dir / "phase310"
        corrupt_p310.mkdir(parents=True)

        # Truncated broken JSON
        (corrupt_p310 / "canary-production-report.json").write_text(
            "{broken_json: true, unexpected_eof", encoding="utf-8"
        )
        (corrupt_p310 / "canary-production-execution.json").write_text(
            "not even json", encoding="utf-8"
        )

        # Must not raise unhandled exception
        status_resp = load_execution_status(corrupt_dir)
        assert status_resp.verified is True
        assert status_resp.aggregate_exposure_usdt == 0.0
        assert status_resp.solvency.zero_balance_drift_verified is True
        assert status_resp.solvency.drift_usdt == 0.0
        assert status_resp.total_orders == 0
        assert len(status_resp.recent_orders) == 0

        # All 3 positions must still be standby
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            pos = status_resp.positions[sym]
            assert pos.position_qty == 0.0
            assert pos.allocated_exposure_usdt == 0.0
            assert pos.state == "STANDBY / SCANNING"
