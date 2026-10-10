"""Phase 313 Milestone 1 Empirical Challenger Stress Test Suite.

Adversarially probes Milestone 1 fallback mechanisms and resilience:
1. Empty directory states:
   - Non-existent directory
   - Completely empty directory
   - Empty phase subdirectories
   - All zero-byte telemetry files
2. Corrupt JSON and invalid JSONL lines:
   - Syntactically corrupt JSON (truncated JSON, syntax errors, invalid binary encoding)
   - Non-dict top-level JSON payloads (arrays, primitives, null)
   - Malformed/null nested schemas (solvency null/string, candidates null,
     orders non-dict, non-numeric mark_price)
   - Invalid JSONL lines interspersed with valid lines
3. Partial directory states:
   - Only phase310/canary-production-report.json present
   - Only phase310/canary-production-execution.json present
   - Only phase311/canary-drill-report.json present
   - Only phase311/canary-orders.jsonl present
4. HTTP API endpoint stability:
   - Verifies GET /api/v1/execution/status never crashes with unhandled 500 error
   - Verifies that corrupt or missing files degrade gracefully to a valid baseline response
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api import create_app
from autonomous_futures.api.app import (
    ExecutionPositionItem,
    ExecutionSolvency,
    ExecutionStatusResponse,
    load_execution_status,
)


def _assert_baseline_solvency(solvency: ExecutionSolvency) -> None:
    """Verifies baseline solvency invariants."""
    assert solvency.starting_equity_usdt == 100.0
    assert solvency.cash_usdt == 100.0
    assert solvency.allocated_margin_usdt == 0.0
    assert solvency.unrealized_pnl_usdt == 0.0
    assert solvency.drift_usdt == 0.0
    assert solvency.zero_balance_drift_verified is True
    assert solvency.cash_reserve_pct == 100.0
    assert solvency.unencumbered_cash_verified is True


def _assert_flat_positions(positions: dict[str, ExecutionPositionItem]) -> None:
    """Verifies that candidate positions are truthfully reported flat."""
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in positions
        pos = positions[sym]
        assert pos.symbol == sym
        assert pos.position_qty == 0.0
        assert pos.allocated_exposure_usdt == 0.0
        assert pos.allocated_margin_usdt == 0.0
        assert pos.unrealized_pnl_usdt == 0.0
        assert pos.state == "STANDBY / SCANNING"
        assert pos.status == "STANDBY / SCANNING"


class TestEmptyDirectoryFallback:
    """Empirical verification of completely empty and absent directory states."""

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist_dir"
        res = load_execution_status(nonexistent)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.status == "MICRO_CAPITAL_ACTIVE"
        assert res.engine_state == "MICRO_CAPITAL_ACTIVE"
        assert res.aggregate_exposure_usdt == 0.0
        assert res.recent_orders == []
        assert res.total_orders == 0
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)

    def test_completely_empty_directory(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        res = load_execution_status(empty_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.aggregate_exposure_usdt == 0.0
        assert res.recent_orders == []
        assert res.total_orders == 0
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)

    def test_empty_phase_subdirectories(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "empty_phases"
        (base_dir / "phase310").mkdir(parents=True, exist_ok=True)
        (base_dir / "phase311").mkdir(parents=True, exist_ok=True)
        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.aggregate_exposure_usdt == 0.0
        assert res.recent_orders == []
        assert res.total_orders == 0
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)

    def test_all_zero_byte_telemetry_files(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "zero_bytes"
        p310 = base_dir / "phase310"
        p311 = base_dir / "phase311"
        p310.mkdir(parents=True, exist_ok=True)
        p311.mkdir(parents=True, exist_ok=True)

        (p310 / "canary-production-report.json").write_text("", encoding="utf-8")
        (p310 / "canary-production-execution.json").write_text("", encoding="utf-8")
        (p311 / "canary-drill-report.json").write_text("", encoding="utf-8")
        (p311 / "canary-orders.jsonl").write_text("", encoding="utf-8")

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.aggregate_exposure_usdt == 0.0
        assert res.recent_orders == []
        assert res.total_orders == 0
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)


class TestCorruptFilesResilience:
    """Empirical verification of resilience against syntax and schema corruptions."""

    def test_syntax_corrupt_json_reports(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "corrupt_json"
        p310 = base_dir / "phase310"
        p311 = base_dir / "phase311"
        p310.mkdir(parents=True, exist_ok=True)
        p311.mkdir(parents=True, exist_ok=True)

        (p310 / "canary-production-report.json").write_text(
            "{ 'invalid': truncated json ...", encoding="utf-8"
        )
        (p310 / "canary-production-execution.json").write_text(
            "[[[not even json", encoding="utf-8"
        )
        (p311 / "canary-drill-report.json").write_text(
            "!!!BINARY_CORRUPTION\x00\xff\xfe", encoding="latin-1"
        )
        (p311 / "canary-orders.jsonl").write_text(
            "bad line 1\n{broken json\n\n", encoding="utf-8"
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.aggregate_exposure_usdt == 0.0
        assert res.recent_orders == []
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)

    def test_jsonl_corrupt_line_does_not_abort_subsequent_valid_lines(
        self, tmp_path: Path
    ) -> None:
        base_dir = tmp_path / "mixed_jsonl"
        p311 = base_dir / "phase311"
        p311.mkdir(parents=True, exist_ok=True)

        lines = [
            json.dumps({
                "event_type": "ORDER_SUBMITTED",
                "client_order_id": "canary-p311-drill-sol-1",
                "order_id": "1001",
                "timestamp_ms": 1791550000000,
            }),
            "GARBAGE MALFORMED LINE NOT JSON",
            "",
            "   ",
            json.dumps({
                "event_type": "ORDER_SUBMITTED",
                "client_order_id": "canary-p311-drill-sol-2",
                "order_id": "1002",
                "timestamp_ms": 1791551000000,
            }),
        ]
        (p311 / "canary-orders.jsonl").write_text("\n".join(lines), encoding="utf-8")

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        order_ids = [o.client_order_id for o in res.recent_orders]
        # In resilient line-by-line parsing, a corrupt middle line must not discard line 2
        assert "canary-p311-drill-sol-1" in order_ids
        assert "canary-p311-drill-sol-2" in order_ids

    def test_non_dict_json_payloads(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "non_dict_json"
        p310 = base_dir / "phase310"
        p311 = base_dir / "phase311"
        p310.mkdir(parents=True, exist_ok=True)
        p311.mkdir(parents=True, exist_ok=True)

        # JSON arrays or literals instead of dict
        (p310 / "canary-production-report.json").write_text(
            json.dumps(["item1", "item2"]), encoding="utf-8"
        )
        (p311 / "canary-drill-report.json").write_text(
            json.dumps(12345), encoding="utf-8"
        )
        (p310 / "canary-production-execution.json").write_text(
            json.dumps(None), encoding="utf-8"
        )
        (p311 / "canary-orders.jsonl").write_text(
            "123\n\"string\"\nnull\n[]\n", encoding="utf-8"
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)

    def test_corrupt_nested_solvency_and_candidates(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "corrupt_schema"
        p310 = base_dir / "phase310"
        p311 = base_dir / "phase311"
        p310.mkdir(parents=True, exist_ok=True)
        p311.mkdir(parents=True, exist_ok=True)

        # Semantically corrupted fields inside valid json dicts
        (p310 / "canary-production-report.json").write_text(
            json.dumps({
                "timestamp_ms": 1791550000000,
                "solvency": None,
                "candidates": None,
                "interlock_blocks_count": None,
                "intra_day_loss_usdt": None,
            }),
            encoding="utf-8",
        )
        (p311 / "canary-drill-report.json").write_text(
            json.dumps({
                "timestamp_ms": 1791551000000,
                "solvency": "invalid_solvency_string",
                "orders": 12345,
                "mark_price": "not_a_float",
            }),
            encoding="utf-8",
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        _assert_baseline_solvency(res.solvency)
        _assert_flat_positions(res.positions)


class TestPartialFilesIngress:
    """Empirical verification of fragmented and single-file states."""

    def test_only_phase310_report(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "only_p310_report"
        p310 = base_dir / "phase310"
        p310.mkdir(parents=True, exist_ok=True)
        (p310 / "canary-production-report.json").write_text(
            json.dumps({
                "timestamp_ms": 1790250000000,
                "solvency": {
                    "starting_equity": 100.0,
                    "cash": 102.5,
                    "realized_pnl": 2.5,
                },
                "candidates": {
                    "BTCUSDT": {"current_price": 68000.0},
                    "ETHUSDT": {"current_price": 2750.0},
                    "SOLUSDT": {"current_price": 185.0},
                },
            }),
            encoding="utf-8",
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.solvency.cash_usdt == 102.5
        assert res.solvency.realized_pnl_usdt == 2.5
        assert res.positions["SOLUSDT"].mark_price == 185.0
        assert res.recent_orders == []

    def test_only_phase310_execution(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "only_p310_exec"
        p310 = base_dir / "phase310"
        p310.mkdir(parents=True, exist_ok=True)
        (p310 / "canary-production-execution.json").write_text(
            json.dumps({
                "orders": [
                    {
                        "order_id": "p310-ord-1",
                        "client_order_id": "canary-p310-sol-1",
                        "symbol": "SOLUSDT",
                        "side": "BUY",
                        "price": 175.0,
                        "quantity": 0.03,
                        "timestamp_ms": 1790250000000,
                    }
                ]
            }),
            encoding="utf-8",
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert len(res.recent_orders) == 1
        assert res.recent_orders[0].client_order_id == "canary-p310-sol-1"
        _assert_baseline_solvency(res.solvency)

    def test_only_phase311_drill_report(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "only_p311_report"
        p311 = base_dir / "phase311"
        p311.mkdir(parents=True, exist_ok=True)
        (p311 / "canary-drill-report.json").write_text(
            json.dumps({
                "timestamp_ms": 1791550000000,
                "mark_price": 186.2,
                "solvency": {
                    "starting_equity": 100.0,
                    "cash": 100.2,
                    "realized_pnl": 0.2,
                },
                "orders": {
                    "entry_order": {
                        "orderId": 5001,
                        "clientOrderId": "canary-p311-drill-sol-entry",
                        "symbol": "SOLUSDT",
                        "side": "BUY",
                        "type": "LIMIT",
                        "price": "185.0",
                        "origQty": "0.03",
                    }
                },
            }),
            encoding="utf-8",
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert res.solvency.cash_usdt == 100.2
        assert res.positions["SOLUSDT"].mark_price == 186.2
        assert len(res.recent_orders) == 1
        assert res.recent_orders[0].client_order_id == "canary-p311-drill-sol-entry"

    def test_only_phase311_orders_jsonl(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "only_p311_jsonl"
        p311 = base_dir / "phase311"
        p311.mkdir(parents=True, exist_ok=True)
        (p311 / "canary-orders.jsonl").write_text(
            json.dumps({
                "event_type": "ORDER_SUBMITTED",
                "client_order_id": "canary-p311-drill-sol-jsonl",
                "order_id": "9001",
                "timestamp_ms": 1791552000000,
            })
            + "\n",
            encoding="utf-8",
        )

        res = load_execution_status(base_dir)
        assert isinstance(res, ExecutionStatusResponse)
        assert res.verified is True
        assert len(res.recent_orders) == 1
        assert res.recent_orders[0].client_order_id == "canary-p311-drill-sol-jsonl"
        _assert_baseline_solvency(res.solvency)


class TestEndpointHTTP500Resilience:
    """Empirical verification that GET /api/v1/execution/status never crashes with 500."""

    @pytest.mark.parametrize(
        "dir_setup",
        [
            "empty",
            "nonexistent",
            "zero_bytes",
            "syntax_corrupt",
            "json_array",
            "null_with_exec",
            "solvency_null",
            "solvency_string",
            "candidates_null",
            "p311_orders_int",
            "p311_mark_price_invalid",
            "partial_p310",
            "partial_p311",
        ],
    )
    def test_endpoint_never_crashes_with_500(
        self, tmp_path: Path, dir_setup: str
    ) -> None:
        target_dir = tmp_path / f"test_{dir_setup}"

        if dir_setup == "empty":
            target_dir.mkdir(parents=True, exist_ok=True)
        elif dir_setup == "nonexistent":
            target_dir = tmp_path / "nonexistent_dir"
        elif dir_setup == "zero_bytes":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                "", encoding="utf-8"
            )
            (target_dir / "phase310" / "canary-production-execution.json").write_text(
                "", encoding="utf-8"
            )
        elif dir_setup == "syntax_corrupt":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase311").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                "{{{broken syntax", encoding="utf-8"
            )
            (target_dir / "phase311" / "canary-orders.jsonl").write_text(
                "broken jsonl\n", encoding="utf-8"
            )
        elif dir_setup == "json_array":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                json.dumps(["corrupted", "array"]), encoding="utf-8"
            )
        elif dir_setup == "null_with_exec":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                "null", encoding="utf-8"
            )
            (target_dir / "phase310" / "canary-production-execution.json").write_text(
                json.dumps({"orders": []}), encoding="utf-8"
            )
        elif dir_setup == "solvency_null":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                json.dumps({"solvency": None}), encoding="utf-8"
            )
        elif dir_setup == "solvency_string":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                json.dumps({"solvency": "invalid_type"}), encoding="utf-8"
            )
        elif dir_setup == "candidates_null":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                json.dumps({"candidates": None}), encoding="utf-8"
            )
        elif dir_setup == "p311_orders_int":
            (target_dir / "phase311").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase311" / "canary-drill-report.json").write_text(
                json.dumps({"orders": 12345}), encoding="utf-8"
            )
        elif dir_setup == "p311_mark_price_invalid":
            (target_dir / "phase311").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase311" / "canary-drill-report.json").write_text(
                json.dumps({"mark_price": "invalid_num"}), encoding="utf-8"
            )
        elif dir_setup == "partial_p310":
            (target_dir / "phase310").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase310" / "canary-production-report.json").write_text(
                json.dumps({"solvency": {"cash": 100.0}}), encoding="utf-8"
            )
        elif dir_setup == "partial_p311":
            (target_dir / "phase311").mkdir(parents=True, exist_ok=True)
            (target_dir / "phase311" / "canary-orders.jsonl").write_text(
                json.dumps({
                    "event_type": "ORDER_SUBMITTED",
                    "client_order_id": "c1",
                    "timestamp_ms": 100,
                })
                + "\n",
                encoding="utf-8",
            )

        app = create_app(
            bundle_path=tmp_path / "missing-bundle.json",
            registry_path=tmp_path / "missing-registry.json",
            research_dir=target_dir,
        )
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/execution/status")

        assert response.status_code == 200, (
            f"Endpoint crashed with {response.status_code} for setup '{dir_setup}': {response.text}"
        )
        payload = response.json()
        assert payload["verified"] is True
        assert payload["status"] == "MICRO_CAPITAL_ACTIVE"
        assert payload["engine_state"] == "MICRO_CAPITAL_ACTIVE"
        assert "solvency" in payload
        assert "positions" in payload
        assert "recent_orders" in payload
