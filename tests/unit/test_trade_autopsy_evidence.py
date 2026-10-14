from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from test_production_remediation import account_data
from test_protective_lifecycle import FILTERS, PLAN

from autonomous_futures.execution.account_evidence import atomic_json
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator
from autonomous_futures.execution.trade_autopsy_evidence import (
    build_closed_trade_autopsy,
    summarize_autopsy_feedback,
)
from autonomous_futures.execution.writer_lease import ExecutionLease
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
    build_runtime_qualification_failure_feedback,
)
from autonomous_futures.research.creator_generator import CreatorGenerationRequest
from autonomous_futures.research.creator_prompts import (
    RUNTIME_RISK_POLICY_GUIDELINES,
    build_creator_revision_messages,
)
from autonomous_futures.research.learner_critic import LearnerCriticRequest, parse_learner_critique
from autonomous_futures.research.learner_critic_evidence import build_learner_critique_evidence
from autonomous_futures.research.learner_critic_provider import build_learner_critic_messages


def test_build_closed_trade_autopsy_handles_unfilled_and_filled_trades() -> None:
    unfilled = build_closed_trade_autopsy(
        PLAN,
        {"entry_id": "afbot-entry-1", "fill_summaries": {}},
        closed_ms=1700000005000,
    )
    assert unfilled["status"] == "UNFILLED_OR_CANCELLED"
    assert unfilled["executed_quantity"] == "0"
    assert unfilled["execution_authority"] is False

    filled = build_closed_trade_autopsy(
        PLAN,
        {
            "entry_id": "afbot-entry-1",
            "fill_summaries": {
                "afbot-entry-1": {
                    "quantity": "2",
                    "quote_quantity": "200",
                    "commission_usdt": "0.04",
                    "realized_pnl_usdt": "0",
                    "first_fill_ms": 1700000001000,
                    "last_fill_ms": 1700000001000,
                },
                "afbot-tp1-1": {
                    "quantity": "2",
                    "quote_quantity": "204",
                    "commission_usdt": "0.0408",
                    "realized_pnl_usdt": "4.0",
                    "first_fill_ms": 1700000061000,
                    "last_fill_ms": 1700000061000,
                },
            },
        },
        closed_ms=1700000062000,
    )
    assert filled["status"] == "FILLED_AND_CLOSED"
    assert filled["source"] == "binance_authenticated_user_trades"
    assert Decimal(filled["gross_pnl_usdt"]) == Decimal("4.0")
    assert Decimal(filled["commission_usdt"]) == Decimal("0.0808")
    assert Decimal(filled["net_pnl_usdt"]) == Decimal("3.9192")
    assert filled["attribution_cause"] == "ORGANIC_ALPHA"
    assert filled["hold_duration_ms"] == 60000
    assert "TP1" in filled["filled_exit_roles"]


def test_summarize_autopsy_feedback_flags_stop_cluster_and_negative_pnl() -> None:
    autopsies = [
        build_closed_trade_autopsy(
            PLAN,
            {
                "entry_id": f"afbot-entry-{idx}",
                "fill_summaries": {
                    f"afbot-entry-{idx}": {
                        "quantity": "2",
                        "quote_quantity": "200",
                        "commission_usdt": "0.04",
                        "realized_pnl_usdt": "0",
                        "first_fill_ms": 1700000000000 + idx * 1000,
                        "last_fill_ms": 1700000000000 + idx * 1000,
                    },
                    f"afbot-stop-{idx}": {
                        "quantity": "2",
                        "quote_quantity": "198",
                        "commission_usdt": "0.10",
                        "realized_pnl_usdt": "-2.0",
                        "first_fill_ms": 1700000010000 + idx * 1000,
                        "last_fill_ms": 1700000010000 + idx * 1000,
                    },
                },
            },
            closed_ms=1700000020000 + idx * 1000,
        )
        for idx in range(5)
    ]
    summary = summarize_autopsy_feedback(autopsies, symbol=PLAN.symbol)
    assert summary["trade_count"] == 5
    assert summary["win_count"] == 0
    assert Decimal(summary["net_pnl_usdt"]) < Decimal("0")
    assert summary["needs_revision"] is True
    assert "negative_or_zero_net_pnl" in summary["failure_reason_codes"]
    assert "stop_loss_regime_mismatch_cluster" in summary["failure_reason_codes"]


def test_lifecycle_coordinator_persists_autopsies_on_trade_close(tmp_path) -> None:
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    try:
        now = int(time.time() * 1000)
        gateway = BinanceFuturesGateway(offline_mode=False)
        gateway.symbol_specs = {
            PLAN.symbol: {
                "tick_size": FILTERS.tick_size,
                "step_size": FILTERS.step_size,
                "min_qty": FILTERS.min_qty,
                "max_qty": FILTERS.max_qty,
                "min_notional": FILTERS.min_notional,
            }
        }
        entry_id = "afbot-" + hashlib.sha256(PLAN.signal_key.encode()).hexdigest()[:30]
        entry_response = {
            "symbol": PLAN.symbol,
            "side": "BUY",
            "clientOrderId": entry_id,
            "orderId": 11,
            "status": "FILLED",
            "origQty": "2",
            "executedQty": "2",
            "price": "100",
            "reduceOnly": False,
        }
        atomic_json(
            tmp_path / "exchange-orders.json",
            {
                entry_id: {
                    "symbol": PLAN.symbol,
                    "side": "BUY",
                    "price": "100",
                    "quantity": "2",
                    "reduce_only": False,
                    "signal_id": PLAN.signal_key,
                    "timestamp_ms": now - 5000,
                    "state": "FILLED",
                    "exchange": entry_response,
                }
            },
        )
        async def get_fills(symbol: str, order_id: int, start_ms: int, end_ms: int):
            if order_id == 11:
                return [
                    {
                        "id": 101,
                        "orderId": 11,
                        "symbol": PLAN.symbol,
                        "side": "BUY",
                        "positionSide": "BOTH",
                        "commissionAsset": "USDT",
                        "qty": "2",
                        "price": "100",
                        "quoteQty": "200",
                        "commission": "0.04",
                        "realizedPnl": "0",
                        "time": now - 4000,
                    }
                ]
            return [
                {
                    "id": 102,
                    "orderId": 12,
                    "symbol": PLAN.symbol,
                    "side": "SELL",
                    "positionSide": "BOTH",
                    "commissionAsset": "USDT",
                    "qty": "2",
                    "price": "102",
                    "quoteQty": "204",
                    "commission": "0.0408",
                    "realizedPnl": "4.0",
                    "time": now - 1000,
                }
            ]

        gateway.get_order_fills = AsyncMock(side_effect=get_fills)
        coordinator = LifecycleCoordinator(gateway, tmp_path, lease=lease)
        coordinator.register_entry(PLAN, entry_id)
        tp1_id = "afbot-tp1-exit"
        coordinator.protective.records[f"PLACE:{tp1_id}"] = {
            "request": {
                "client_id": tp1_id,
                "plan_key": PLAN.signal_key,
                "symbol": PLAN.symbol,
                "role": "TP1",
                "operation": "PLACE",
                "order_type": "LIMIT",
                "quantity": "2",
                "price": "102",
                "side": "SELL",
                "reduce_only": True,
            },
            "state": "FILLED",
            "exchange": {
                "symbol": PLAN.symbol,
                "side": "SELL",
                "clientOrderId": tp1_id,
                "orderId": 12,
                "status": "FILLED",
                "origQty": "2",
                "executedQty": "2",
                "price": "102",
                "reduceOnly": True,
            },
        }
        data = account_data()
        data["positions"] = []
        atomic_json(tmp_path / "exchange-account.json", data)
        assert asyncio.run(coordinator.advance(data["timestamp_ms"])) == ()
        trade = coordinator.trades[PLAN.signal_key]
        assert trade["closed"] is True
        assert trade["outcome_autopsy"]["status"] == "FILLED_AND_CLOSED"
        assert Decimal(trade["outcome_autopsy"]["net_pnl_usdt"]) == Decimal("3.9192")
        autopsies_file = json.loads((tmp_path / "trade-autopsies.json").read_text(encoding="utf-8"))
        assert len(autopsies_file["autopsies"]) == 1
        assert autopsies_file["summary"]["trade_count"] == 1
        assert autopsies_file["summary"]["win_count"] == 1
    finally:
        lease.close()


def test_creator_revision_messages_include_autopsy_feedback_and_runtime_policy() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-autopsy-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=2,
        forbidden_candidate_ids=("cand-doge-meanrev-002",),
    )
    feedback = CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": "cand-doge-meanrev-002",
            "candidate_artifact_hash": "a" * 64,
            "bundle_hash": "b" * 64,
            "dataset_registry_hash": "c" * 64,
            "qualification_hash": "d" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [
                {
                    "gate_id": "oos_profit_factor_min",
                    "passed": False,
                    "observed": "0.85",
                    "threshold": "1",
                    "comparator": "gte",
                    "reason_code": "oos_profit_factor_below_threshold",
                }
            ],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )
    critic_request = LearnerCriticRequest(
        research_run_id="run-critic-autopsy-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=("feedback/hash",),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )
    critique_evidence = build_learner_critique_evidence(
        request=critic_request,
        critique=parse_learner_critique(
            {
                "review_id": "review-critic-autopsy-001",
                "research_run_id": "run-critic-autopsy-001",
                "candidate_id": feedback.candidate_id,
                "decision": "revise",
                "failure_reason_codes": ["oos_profit_factor_below_threshold"],
                "revision_actions": ["change_entry_threshold"],
            }
        ),
        evidence_id="critic-evidence-autopsy-001",
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    messages = build_creator_revision_messages(
        request,
        bundle_hash="b" * 64,
        symbol="DOGEUSDT",
        feedback=feedback,
        critique_evidence=critique_evidence,
        autopsy_feedback={
            "schema": "runtime-autopsy-feedback-summary-v1",
            "symbol": "DOGEUSDT",
            "failure_reason_codes": ["stop_loss_regime_mismatch_cluster"],
            "needs_revision": True,
        },
    )
    assert "Authenticated post-trade autopsy feedback=" in messages[1]["content"]
    assert "stop_loss_regime_mismatch_cluster" in messages[1]["content"]
    assert RUNTIME_RISK_POLICY_GUIDELINES in messages[1]["content"]


def test_xrp_holdout_rejection_and_autopsy_bridge_into_learner_and_creator() -> None:
    import dataclasses

    report_path = Path(
        "artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    xrp_plan = dataclasses.replace(
        PLAN,
        signal_key="XRPUSDT:1700000000000:LONG",
        symbol="XRPUSDT",
    )
    autopsies = [
        build_closed_trade_autopsy(
            xrp_plan,
            {
                "entry_id": "afbot-xrp-1",
                "fill_summaries": {
                    "afbot-xrp-1": {
                        "quantity": "100",
                        "quote_quantity": "50",
                        "commission_usdt": "0.02",
                        "realized_pnl_usdt": "0",
                        "first_fill_ms": 1700000001000,
                        "last_fill_ms": 1700000001000,
                    },
                    "afbot-stop-1": {
                        "quantity": "100",
                        "quote_quantity": "49",
                        "commission_usdt": "0.02",
                        "realized_pnl_usdt": "-1.0",
                        "first_fill_ms": 1700000010000,
                        "last_fill_ms": 1700000010000,
                    },
                },
            },
            closed_ms=1700000015000,
        )
    ]

    feedback = build_runtime_qualification_failure_feedback(
        report,
        autopsy_records=autopsies,
    )
    assert feedback is not None
    assert feedback.candidate_id == "cand-macro-scalper-xrpusdt-d-4-0-t3-0"
    assert (
        feedback.qualification_hash
        == "92d4ce70f71e709699403b3fd60243b39fc5ed953e90040c16901d1d548e1597"
    )
    assert "oos_trades_below_threshold" in feedback.failure_reason_codes
    assert "oos_profitable_windows_below_threshold" in feedback.failure_reason_codes
    assert "autopsy_realized_net_pnl_negative" in feedback.failure_reason_codes
    assert "stop_loss_regime_mismatch_cluster" in feedback.failure_reason_codes

    critic_req = LearnerCriticRequest(
        research_run_id="run-critic-xrp-holdout-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=(
            f"feedback/{feedback.qualification_hash}",
            f"policy/{feedback.qualification_policy_id}",
        ),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )
    _, critic_user = build_learner_critic_messages(critic_req)
    assert "oos_trades_below_threshold" in critic_user["content"]
    assert "autopsy_realized_net_pnl_negative" in critic_user["content"]
    assert "stop_loss_regime_mismatch_cluster" in critic_user["content"]

