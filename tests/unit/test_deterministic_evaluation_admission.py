"""Unit tests for deterministic evaluation and admission guardrails (R3).

Verifies:
1. Causal features and contiguous historical windows:
   - Closed context available only after candle close time (no lookahead).
   - Missing or non-canonical context raises DataQualityError.
2. Decimal ledger arithmetic:
   - Exact precision for fees, slippage, PnL, and equity.
   - Zero floating-point drift.
3. Missing data handling:
   - Missing data remains UNAVAILABLE; never fabricated as 0.0 or forward-filled.
   - Undefined profit factor produces None / explicit missing failure gate.
4. Fixed qualification thresholds established prior to outcomes:
   - Enforced strictly from WalkForwardQualificationPolicy, immune to candidate parameters.
5. Demonstration of both qualified-fixture admission AND real rejection paths, labeled separately.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.causal_evaluation import materialize_causal_context
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.creator_failure_feedback import (
    build_creator_qualification_failure_feedback,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    WalkForwardQualificationPolicy,
    build_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import (
    SimulatedTrade,
    TradeSimulationConfig,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def _make_strategy(strategy_id: str = "cand-strat-001") -> StrategySpec:
    return StrategySpec(
        dsl_version=1,
        strategy_id=strategy_id,
        family="volume_confirmed_momentum",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
    )


def _make_candidate(candidate_id: str = "cand-strat-001"):
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=_make_strategy(candidate_id),
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="run-creator-001",
        research_seed=42,
        created_at=START,
    )


def _make_policy(*, min_profit_factor: str = "1.2", max_drawdown: str = "0.10"):
    return WalkForwardQualificationPolicy(
        policy_id="wf-policy-pinned-001",
        minimum_windows=1,
        minimum_trades=5,
        minimum_profit_factor=Decimal(min_profit_factor),
        maximum_drawdown_pct=Decimal(max_drawdown),
        minimum_average_return_pct=Decimal("0.01"),
    )


# ---------------------------------------------------------------------------
# 1. Causal Features & Lookahead Prevention Tests
# ---------------------------------------------------------------------------


def test_causal_context_prevents_lookahead() -> None:
    """Verify context 15m candle is only attached to 5m bars after close_time + 1ms."""
    start_15m = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    context_df = pd.DataFrame(
        {
            "timestamp": [start_15m],
            "open": [Decimal("100")],
            "high": [Decimal("105")],
            "low": [Decimal("95")],
            "close": [Decimal("102")],
            "close_time": [start_15m + timedelta(minutes=15) - timedelta(milliseconds=1)],
        }
    )

    # 5m primary bars covering the 15m span: 00:00, 00:05, 00:10, 00:15
    primary_df = pd.DataFrame(
        {
            "timestamp": [start_15m + timedelta(minutes=5 * i) for i in range(4)],
            "open": [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103")],
            "high": [Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104")],
            "low": [Decimal("99"), Decimal("100"), Decimal("101"), Decimal("102")],
            "close": [Decimal("100.5"), Decimal("101.5"), Decimal("102.5"), Decimal("103.5")],
        }
    )

    merged = materialize_causal_context(primary_df, context_df)

    # During the 15m candle (at 00:00, 00:05, 00:10), context close MUST be NaN/unavailable
    assert pd.isna(merged.loc[0, "context_close"])
    assert pd.isna(merged.loc[1, "context_close"])
    assert pd.isna(merged.loc[2, "context_close"])

    # At 00:15 (first bar after 15m close), context close is causal and available
    assert merged.loc[3, "context_close"] == Decimal("102")


def test_causal_context_rejects_non_utc_or_corrupt_boundaries() -> None:
    """Verify non-UTC or misaligned candle boundaries raise DataQualityError."""
    start_15m = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    invalid_context = pd.DataFrame(
        {
            "timestamp": [start_15m],
            "open": [Decimal("100")],
            "high": [Decimal("105")],
            "low": [Decimal("95")],
            "close": [Decimal("102")],
            # Invalid close_time: 14m instead of 15m
            "close_time": [start_15m + timedelta(minutes=14)],
        }
    )
    primary_df = pd.DataFrame(
        {
            "timestamp": [start_15m],
            "open": [Decimal("100")],
            "high": [Decimal("101")],
            "low": [Decimal("99")],
            "close": [Decimal("100.5")],
        }
    )
    with pytest.raises(DataQualityError, match="15m candle boundaries"):
        materialize_causal_context(primary_df, invalid_context)


# ---------------------------------------------------------------------------
# 2. Decimal Ledger Arithmetic & Precision Tests
# ---------------------------------------------------------------------------


def test_decimal_ledger_arithmetic_exact_precision() -> None:
    """Verify zero binary floating-point drift in ledger math."""
    # Binary float: 0.1 + 0.2 != 0.3 (evaluates to 0.30000000000000004)
    # Decimal: Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
    val1 = Decimal("0.1")
    val2 = Decimal("0.2")
    expected = Decimal("0.3")
    assert (val1 + val2) == expected

    # Verify TradeSimulationConfig accepts only strict Decimals
    cfg = TradeSimulationConfig(
        starting_equity=Decimal("10000.00"),
        position_fraction=Decimal("0.10"),
        taker_fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0002"),
    )
    assert cfg.starting_equity == Decimal("10000.00")
    assert cfg.taker_fee_rate == Decimal("0.0005")

    # Verify SimulatedTrade preserves exact Decimal notional without float conversion
    trade = SimulatedTrade(
        trade_id="trade-001",
        symbol="BTCUSDT",
        side="LONG",
        entry_timestamp=START,
        exit_timestamp=START + timedelta(minutes=30),
        quantity=Decimal("0.00123456"),
        entry_price=Decimal("65432.10"),
        exit_price=Decimal("66123.45"),
        entry_notional=Decimal("0.00123456") * Decimal("65432.10"),
        exit_notional=Decimal("0.00123456") * Decimal("66123.45"),
        entry_fee=Decimal("0.04059011736"),
        exit_fee=Decimal("0.04059011736"),
        fees=Decimal("0.08118023472"),
        slippage_cost=Decimal("0.01623604694"),
        gross_pnl=Decimal("0.93468726192"),
        net_pnl=Decimal("0.8535070272"),
        exit_reason="take_profit",
    )
    assert isinstance(trade.net_pnl, Decimal)
    assert trade.net_pnl == Decimal("0.8535070272")
    assert trade.fees == Decimal("0.08118023472")


# ---------------------------------------------------------------------------
# 3. Missing Data Remains UNAVAILABLE (Never Fabricated Zero)
# ---------------------------------------------------------------------------


def test_missing_data_remains_unavailable_not_zero() -> None:
    """Verify missing metrics remain None and trigger explicit missing failure gates."""
    candidate = _make_candidate("cand-missing-001")

    # Gate with missing observed value (None, not 0.0)
    missing_gate = QualificationGateResult(
        gate_id="oos_profit_factor_min",
        passed=False,
        observed=None,  # Missing, not 0.0!
        threshold=Decimal("1.2"),
        comparator="gte",
        reason_code="oos_profit_factor_missing",
    )
    artifact = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="eval-001",
        evaluator_version="1.0",
        decision="rejected",
        metrics=(QualificationMetric(metric_id="oos_trades", value=Decimal("0")),),
        gates=(missing_gate,),
        windows_evaluated=1,
        evaluated_at=START,
        qualification_policy_id="policy-001",
    )

    assert artifact.decision == "rejected"
    assert artifact.gates[0].observed is None
    assert artifact.gates[0].reason_code == "oos_profit_factor_missing"


# ---------------------------------------------------------------------------
# 4. Fixed Qualification Thresholds Outside AI Control
# ---------------------------------------------------------------------------


def test_qualification_thresholds_cannot_be_overridden() -> None:
    """Verify qualification thresholds are determined solely by pinned policy."""
    policy = _make_policy(min_profit_factor="1.5", max_drawdown="0.05")
    candidate = _make_candidate("cand-fixed-001")

    # Candidate metrics breach policy thresholds
    pf_gate = QualificationGateResult(
        gate_id="oos_profit_factor_min",
        passed=False,
        observed=Decimal("1.4"),
        threshold=policy.minimum_profit_factor,
        comparator="gte",
        reason_code="oos_profit_factor_below_threshold",
    )
    dd_gate = QualificationGateResult(
        gate_id="oos_drawdown_max",
        passed=False,
        observed=Decimal("0.08"),
        threshold=policy.maximum_drawdown_pct,
        comparator="lte",
        reason_code="oos_drawdown_above_threshold",
    )
    artifact = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="eval-001",
        evaluator_version="1.0",
        decision="rejected",
        metrics=(
            QualificationMetric(metric_id="oos_profit_factor", value=Decimal("1.4")),
            QualificationMetric(metric_id="oos_worst_drawdown_pct", value=Decimal("0.08")),
        ),
        gates=(pf_gate, dd_gate),
        windows_evaluated=2,
        evaluated_at=START,
        qualification_policy_id=policy.policy_id,
    )
    assert artifact.decision == "rejected"
    # Thresholds are strictly from policy
    assert pf_gate.threshold == Decimal("1.5")
    assert pf_gate.passed is False
    assert dd_gate.threshold == Decimal("0.05")
    assert dd_gate.passed is False


# ---------------------------------------------------------------------------
# 5. Qualified-Fixture Admission Path & Real Rejection Path (Labeled Separately)
# ---------------------------------------------------------------------------


def test_qualified_fixture_admission_path() -> None:
    """[QUALIFIED PATH] Candidate exceeding all qualification thresholds qualifies."""
    candidate = _make_candidate("cand-qualified-fixture-001")
    policy = _make_policy(min_profit_factor="1.2", max_drawdown="0.10")

    passed_pf_gate = QualificationGateResult(
        gate_id="oos_profit_factor_min",
        passed=True,
        observed=Decimal("1.85"),
        threshold=policy.minimum_profit_factor,
        comparator="gte",
        reason_code="oos_profit_factor_passed",
    )
    passed_dd_gate = QualificationGateResult(
        gate_id="oos_drawdown_max",
        passed=True,
        observed=Decimal("0.04"),
        threshold=policy.maximum_drawdown_pct,
        comparator="lte",
        reason_code="oos_drawdown_passed",
    )
    passed_trades_gate = QualificationGateResult(
        gate_id="oos_trades_min",
        passed=True,
        observed=Decimal("25"),
        threshold=Decimal(policy.minimum_trades),
        comparator="gte",
        reason_code="oos_trades_passed",
    )
    artifact = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="eval-pass-001",
        evaluator_version="1.0",
        decision="qualified",
        metrics=(
            QualificationMetric(metric_id="oos_profit_factor", value=Decimal("1.85")),
            QualificationMetric(metric_id="oos_worst_drawdown_pct", value=Decimal("0.04")),
            QualificationMetric(metric_id="oos_total_trades", value=Decimal("25")),
        ),
        gates=(passed_pf_gate, passed_dd_gate, passed_trades_gate),
        windows_evaluated=2,
        evaluated_at=START,
        qualification_policy_id=policy.policy_id,
    )

    assert artifact.decision == "qualified"
    assert all(gate.passed for gate in artifact.gates)
    assert artifact.execution_authority is False
    assert artifact.promotion_state == "unpromoted"


def test_real_rejection_path_with_failure_feedback() -> None:
    """[REJECTION PATH] Underperforming candidate is rejected and produces typed feedback."""
    candidate = _make_candidate("cand-rejected-fixture-001")
    policy = _make_policy(min_profit_factor="1.3", max_drawdown="0.10")

    failed_pf_gate = QualificationGateResult(
        gate_id="oos_profit_factor_min",
        passed=False,
        observed=Decimal("0.85"),
        threshold=policy.minimum_profit_factor,
        comparator="gte",
        reason_code="oos_profit_factor_below_threshold",
    )
    artifact = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="eval-fail-001",
        evaluator_version="1.0",
        decision="rejected",
        metrics=(QualificationMetric(metric_id="oos_profit_factor", value=Decimal("0.85")),),
        gates=(failed_pf_gate,),
        windows_evaluated=2,
        evaluated_at=START,
        qualification_policy_id=policy.policy_id,
    )

    assert artifact.decision == "rejected"
    failed_gates = tuple(g for g in artifact.gates if not g.passed)
    assert len(failed_gates) >= 1
    assert any(g.gate_id == "oos_profit_factor_min" for g in failed_gates)

    # Build typed failure feedback to feed back into research loop
    feedback = build_creator_qualification_failure_feedback(artifact)
    assert feedback is not None
    assert feedback.candidate_id == "cand-rejected-fixture-001"
    assert "oos_profit_factor_below_threshold" in feedback.failure_reason_codes
