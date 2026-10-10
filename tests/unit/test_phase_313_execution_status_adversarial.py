"""Adversarial stress-test and empirical challenger suite for Milestone 1.

Verifies GET /api/v1/execution/status endpoint, Pydantic schema contracts,
solvency zero-drift mathematical invariants, flat position confinement,
authentic client order ID provenance, and resilience under corrupt artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from autonomous_futures.api.app import (
    ExecutionSolvency,
    ExecutionStatusResponse,
    create_app,
)


def _assert_zero_drift_invariant(solvency: dict[str, Any] | ExecutionSolvency) -> None:
    """Assert mathematical double-entry zero-drift invariant strictly holds."""
    if isinstance(solvency, ExecutionSolvency):
        s_dict = solvency.model_dump()
    else:
        s_dict = solvency

    cash_usdt = float(s_dict["cash_usdt"])
    allocated_margin_usdt = float(s_dict["allocated_margin_usdt"])
    unrealized_pnl_usdt = float(s_dict["unrealized_pnl_usdt"])
    starting_equity_usdt = float(s_dict["starting_equity_usdt"])
    realized_pnl_usdt = float(s_dict["realized_pnl_usdt"])

    left_side = cash_usdt + allocated_margin_usdt + unrealized_pnl_usdt
    right_side = starting_equity_usdt + realized_pnl_usdt

    drift = abs(left_side - right_side)
    assert drift < 1e-9, (
        f"Zero-drift invariant violated! Drift={drift}: "
        f"{cash_usdt} + {allocated_margin_usdt} + {unrealized_pnl_usdt} != "
        f"{starting_equity_usdt} + {realized_pnl_usdt}"
    )
    assert s_dict["drift_usdt"] == 0.0 or abs(float(s_dict["drift_usdt"])) < 1e-9
    assert s_dict["zero_balance_drift_verified"] is True


def test_adversarial_live_execution_status_endpoint() -> None:
    """Empirically test live endpoint using FastAPI TestClient against real artifacts."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    # 1. Pydantic schema validation
    raw_payload = response.json()
    validated = ExecutionStatusResponse.model_validate(raw_payload)
    assert validated.verified is True
    assert validated.status == "MICRO_CAPITAL_ACTIVE"
    assert validated.engine_state == "MICRO_CAPITAL_ACTIVE"

    # 2. Assert all 3 candidate pairs (BTCUSDT, ETHUSDT, SOLUSDT) are flat and STANDBY / SCANNING
    positions = raw_payload["positions"]
    assert len(positions) == 3
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in positions, f"Missing candidate pair {sym}"
        p = positions[sym]
        assert p["symbol"] == sym
        assert p["position_qty"] == 0.0, f"Expected 0.0 qty for {sym}, got {p['position_qty']}"
        assert p["allocated_exposure_usdt"] == 0.0, (
            f"Expected 0.0 exposure for {sym}, got {p['allocated_exposure_usdt']}"
        )
        assert p["status"] == "STANDBY / SCANNING"
        assert p["state"] == "STANDBY / SCANNING"
        assert p["allocated_margin_usdt"] == 0.0
        assert p["unrealized_pnl_usdt"] == 0.0

    # Check candidate_allocations list matches positions
    assert len(validated.candidate_allocations) == 3
    for alloc in validated.candidate_allocations:
        assert alloc.position_qty == 0.0
        assert alloc.allocated_exposure_usdt == 0.0
        assert alloc.status == "STANDBY / SCANNING"

    # 3. Assert aggregate exposure is exactly 0.0
    assert raw_payload["aggregate_exposure_usdt"] == 0.0
    assert validated.aggregate_exposure_usdt == 0.0

    # 4. Assert zero-drift invariant holds
    _assert_zero_drift_invariant(raw_payload["solvency"])

    # 5. Assert recent_orders contains authentic client order IDs
    orders = raw_payload["recent_orders"]
    assert len(orders) > 0, "recent_orders must not be empty"
    assert raw_payload["total_orders"] == len(orders)

    cids = [o["client_order_id"] for o in orders]
    # Verify no fake phase 309 test records
    assert not any(cid.startswith("ord-p309-") for cid in cids), (
        "Stale Phase 309 placeholder orders found in recent_orders"
    )

    # Must contain both Phase 311 and Phase 310 genuine order IDs
    p311_orders = [cid for cid in cids if cid.startswith("canary-p311-")]
    p310_orders = [cid for cid in cids if cid.startswith("canary-p310-")]
    assert len(p311_orders) > 0, "No canary-p311- orders found"
    assert len(p310_orders) > 0, "No canary-p310- orders found"

    # Verify monotonic descending order by timestamp_ms
    timestamps = [o["timestamp_ms"] for o in orders]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1], (
            f"Monotonic descending ordering violated at index {i}: "
            f"{timestamps[i]} < {timestamps[i + 1]} (order: {orders[i]['client_order_id']})"
        )


def test_adversarial_corrupted_json_resilience(tmp_path: Path) -> None:
    """Stress test when research artifact files are corrupted, truncated, or invalid JSON."""
    corrupt_dir = tmp_path / "corrupt_research"
    p310_dir = corrupt_dir / "phase310"
    p311_dir = corrupt_dir / "phase311"
    p310_dir.mkdir(parents=True)
    p311_dir.mkdir(parents=True)

    # Corrupt JSON syntax in reports
    (p310_dir / "canary-production-report.json").write_text("{CORRUPT_JSON", encoding="utf-8")
    (p310_dir / "canary-production-execution.json").write_text("NOT_JSON", encoding="utf-8")
    (p311_dir / "canary-drill-report.json").write_text('{"unterminated": ', encoding="utf-8")
    # Corrupt lines in orders jsonl
    (p311_dir / "canary-orders.jsonl").write_text(
        'INVALID_JSON_LINE\n\n{"event_type": "UNKNOWN"}\n', encoding="utf-8"
    )

    app = create_app(research_dir=corrupt_dir)
    client = TestClient(app)

    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200, "Corrupted files should not cause HTTP 500"

    payload = response.json()
    validated = ExecutionStatusResponse.model_validate(payload)
    assert validated.verified is True
    assert validated.aggregate_exposure_usdt == 0.0

    # Invariant must still hold in fallback state
    _assert_zero_drift_invariant(payload["solvency"])

    # Positions must be safely flat
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert payload["positions"][sym]["position_qty"] == 0.0
        assert payload["positions"][sym]["allocated_exposure_usdt"] == 0.0
        assert payload["positions"][sym]["status"] == "STANDBY / SCANNING"


def test_adversarial_p310_only_resilience(tmp_path: Path) -> None:
    """Stress test when only Phase 310 telemetry is present."""
    p310_only_dir = tmp_path / "p310_only"
    p310_dir = p310_only_dir / "phase310"
    p310_dir.mkdir(parents=True)

    p310_report_data = {
        "phase": "phase_310",
        "timestamp_ms": 1791511262886,
        "engine_state": "MICRO_CAPITAL_ACTIVE",
        "solvency": {
            "starting_equity": 100.0,
            "cash": 100.2038066,
            "allocated_margin": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.2038066,
            "total_equity": 100.2038066,
            "drift": 0.0,
            "zero_balance_drift": True,
        },
        "candidates": {
            "BTCUSDT": {"current_price": 95000.0},
            "ETHUSDT": {"current_price": 2750.0},
            "SOLUSDT": {"current_price": 171.0},
        },
    }
    (p310_dir / "canary-production-report.json").write_text(
        json.dumps(p310_report_data), encoding="utf-8"
    )

    app = create_app(research_dir=p310_only_dir)
    client = TestClient(app)

    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200

    payload = response.json()
    _assert_zero_drift_invariant(payload["solvency"])
    assert payload["solvency"]["cash_usdt"] == 100.2038066
    assert payload["solvency"]["realized_pnl_usdt"] == 0.2038066
    assert payload["aggregate_exposure_usdt"] == 0.0
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert payload["positions"][sym]["position_qty"] == 0.0


def test_adversarial_p311_only_resilience(tmp_path: Path) -> None:
    """Stress test when only Phase 311 telemetry is present."""
    p311_only_dir = tmp_path / "p311_only"
    p311_dir = p311_only_dir / "phase311"
    p311_dir.mkdir(parents=True)

    p311_report_data = {
        "phase": "phase_311",
        "timestamp_ms": 1791554786397,
        "symbol": "SOLUSDT",
        "mark_price": 185.0,
        "solvency": {
            "starting_equity": 100.0,
            "cash": 99.99889,
            "allocated_margin": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": -0.00111,
            "total_equity": 99.99889,
            "drift": 0.0,
            "zero_balance_drift": True,
        },
    }
    (p311_dir / "canary-drill-report.json").write_text(
        json.dumps(p311_report_data), encoding="utf-8"
    )

    app = create_app(research_dir=p311_only_dir)
    client = TestClient(app)

    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200

    payload = response.json()
    _assert_zero_drift_invariant(payload["solvency"])
    assert payload["solvency"]["cash_usdt"] == 99.99889
    assert payload["solvency"]["realized_pnl_usdt"] == -0.00111
    assert payload["aggregate_exposure_usdt"] == 0.0


def test_adversarial_out_of_order_orders_jsonl_sorting(tmp_path: Path) -> None:
    """Stress test that unsorted order events in JSONL are sorted descending by timestamp."""
    custom_dir = tmp_path / "custom_research"
    p311_dir = custom_dir / "phase311"
    p311_dir.mkdir(parents=True)

    # Write orders in scrambled timestamp order
    order_lines = [
        {
            "event_type": "ORDER_SUBMITTED",
            "client_order_id": "canary-p311-ord-1",
            "order_id": "1",
            "timestamp_ms": 1000,
        },
        {
            "event_type": "ORDER_SUBMITTED",
            "client_order_id": "canary-p311-ord-3",
            "order_id": "3",
            "timestamp_ms": 3000,
        },
        {
            "event_type": "ORDER_SUBMITTED",
            "client_order_id": "canary-p311-ord-2",
            "order_id": "2",
            "timestamp_ms": 2000,
        },
        {
            "event_type": "ORDER_SUBMITTED",
            "client_order_id": "canary-p311-ord-4",
            "order_id": "4",
            "timestamp_ms": 4000,
        },
    ]
    with open(p311_dir / "canary-orders.jsonl", "w", encoding="utf-8") as f:
        for ol in order_lines:
            f.write(json.dumps(ol) + "\n")

    p311_report = {
        "phase": "phase_311",
        "timestamp_ms": 5000,
        "solvency": {"starting_equity": 100.0, "cash": 100.0, "realized_pnl": 0.0},
    }
    (p311_dir / "canary-drill-report.json").write_text(json.dumps(p311_report), encoding="utf-8")

    app = create_app(research_dir=custom_dir)
    client = TestClient(app)

    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200
    orders = response.json()["recent_orders"]
    assert len(orders) == 4
    timestamps = [o["timestamp_ms"] for o in orders]
    assert timestamps == [4000, 3000, 2000, 1000]


def test_adversarial_http_methods() -> None:
    """Stress test unpermitted HTTP methods against /api/v1/execution/status."""
    app = create_app()
    client = TestClient(app)

    # POST should return 405 Method Not Allowed
    r_post = client.post("/api/v1/execution/status")
    assert r_post.status_code == 405

    # DELETE should return 405 Method Not Allowed
    r_del = client.delete("/api/v1/execution/status")
    assert r_del.status_code == 405

    # PUT should return 405 Method Not Allowed
    r_put = client.put("/api/v1/execution/status")
    assert r_put.status_code == 405


def test_defect_non_dict_json_report_crashes_endpoint(tmp_path: Path) -> None:
    bad_dir = tmp_path / "bad_research"
    p310_dir = bad_dir / "phase310"
    p310_dir.mkdir(parents=True)
    payload = json.dumps(["item1", "item2"])
    (p310_dir / "canary-production-report.json").write_text(payload, encoding="utf-8")
    app = create_app(research_dir=bad_dir)
    client = TestClient(app)
    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_defect_null_nested_solvency_crashes_endpoint(tmp_path: Path) -> None:
    bad_dir = tmp_path / "bad_research"
    p310_dir = bad_dir / "phase310"
    p310_dir.mkdir(parents=True)
    (p310_dir / "canary-production-report.json").write_text(
        json.dumps({"timestamp_ms": 1000, "solvency": None}), encoding="utf-8"
    )
    app = create_app(research_dir=bad_dir)
    client = TestClient(app)
    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_defect_null_nested_candidates_crashes_endpoint(tmp_path: Path) -> None:
    bad_dir = tmp_path / "bad_research"
    p310_dir = bad_dir / "phase310"
    p310_dir.mkdir(parents=True)
    (p310_dir / "canary-production-report.json").write_text(
        json.dumps(
            {
                "timestamp_ms": 1000,
                "solvency": {"starting_equity": 100.0, "cash": 100.0, "realized_pnl": 0.0},
                "candidates": None,
            }
        ),
        encoding="utf-8",
    )
    app = create_app(research_dir=bad_dir)
    client = TestClient(app)
    response = client.get("/api/v1/execution/status")
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_defect_api_init_missing_exports() -> None:
    import autonomous_futures.api as af_api

    assert hasattr(af_api, "ExecutionStatusResponse")
    assert hasattr(af_api, "ExecutionSolvency")
    assert hasattr(af_api, "ExecutionPositionItem")
    assert hasattr(af_api, "ExecutionOrderItem")
    assert hasattr(af_api, "load_execution_status")

    from autonomous_futures.api import (
        ExecutionOrderItem,
        ExecutionPositionItem,
        ExecutionSolvency,
        ExecutionStatusResponse,
        load_execution_status,
    )

    assert ExecutionStatusResponse is not None
    assert ExecutionSolvency is not None
    assert ExecutionPositionItem is not None
    assert ExecutionOrderItem is not None
    assert callable(load_execution_status)
