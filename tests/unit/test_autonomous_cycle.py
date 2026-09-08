"""Unit tests for the bounded closed-loop Autonomous Pipeline Cycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.pipeline.autonomous_cycle import (
    AutonomousCycleConfig,
    execute_autonomous_cycle,
)
from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.creator_generator import CreatorGenerationRequest
from autonomous_futures.research.learner_critic import LearnerCriticRequest
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    SimulatedTrade,
    TradeSimulationResult,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 8, 14, 0, tzinfo=UTC)


def _make_bars_frame(n_bars: int = 100, base_price: float = 100.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    timestamps = pd.date_range(start, periods=n_bars, freq="5min", tz="UTC")
    rows = []
    price = base_price
    for i, t in enumerate(timestamps):
        delta = 1.0 if (i % 8) < 4 else -1.0
        price = max(10.0, price + delta)
        rows.append(
            {
                "timestamp": t,
                "open": price - 0.2,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _build_test_candidate(cand_id: str, stop_atr: str = "1.5") -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cand_id,
        family="range_mean_reversion",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_atr),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="run-initial-001",
        research_seed=1,
        created_at=NOW,
    )


def _make_cached_window(symbol: str = "BTCUSDT") -> CachedEvaluationWindow:
    df = _make_bars_frame(100)
    spec = CachedEvaluationWindowSpec(
        window_id="window-001",
        symbol=symbol,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        time_start=datetime(2026, 1, 1, tzinfo=UTC),
        time_end=datetime(2026, 1, 1, 8, 20, tzinfo=UTC),
    )
    return CachedEvaluationWindow(spec=spec, frame=df)


def _policy(
    min_profit_factor: str = "1.0", max_drawdown: str = "20.0"
) -> WalkForwardQualificationPolicy:
    return WalkForwardQualificationPolicy(
        policy_id="policy-cycle-001",
        minimum_windows=1,
        minimum_trades=1,
        minimum_profit_factor=Decimal(min_profit_factor),
        maximum_drawdown_pct=Decimal(max_drawdown),
        minimum_average_return_pct=Decimal("0.0"),
    )


def test_autonomous_cycle_successful_end_to_end(tmp_path: Path):
    initial_cand = _build_test_candidate("cand-initial-001", stop_atr="0.5")
    window = _make_cached_window()

    # Prior feedback: initial candidate failed profit factor
    feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash="1" * 64,
        qualification_policy_id="policy-cycle-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.8"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    # Injected critic: advises widening stop multiplier
    def mock_critic_transport(req: LearnerCriticRequest) -> dict:
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier", "tighten_entry_threshold"],
        }

    # Injected creator: generates revised proposal with wider stop
    def mock_creator_transport(req: CreatorGenerationRequest) -> dict:
        cand_id = "cand-revised-002"
        return {
            "proposal_id": "proposal-revised-002",
            "research_run_id": req.research_run_id,
            "hypothesis": "Wider stop ATR accommodates volatility",
            "expected_regime": "trending",
            "novelty_reason": "Learner critique feedback incorporated",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": cand_id,
                "family": "range_mean_reversion",
                "universe": {
                    "symbols": ["BTCUSDT"],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
                "entry": {"long": "rsi <= 35", "short": "rsi >= 65"},
                "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.1"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("4.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    config = AutonomousCycleConfig(
        cycle_id="cycle-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_policy=_policy(min_profit_factor="0.0"),  # permissive for test pass
        artifact_root=tmp_path / "artifacts",
        max_attempts=1,
    )

    def _mock_winning_simulator(c, frame, w):
        ts = frame["timestamp"].iloc[-1].to_pydatetime()
        t1 = SimulatedTrade(
            trade_id="t1",
            symbol=w.spec.symbol,
            side="LONG",
            entry_timestamp=ts - timedelta(hours=2),
            exit_timestamp=ts - timedelta(hours=1),
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            exit_price=Decimal("110"),
            entry_notional=Decimal("100"),
            exit_notional=Decimal("110"),
            entry_fee=Decimal("0.05"),
            exit_fee=Decimal("0.05"),
            fees=Decimal("0.10"),
            slippage_cost=Decimal("0.02"),
            gross_pnl=Decimal("10.00"),
            net_pnl=Decimal("9.90"),
            exit_reason="take_profit",
        )
        t2 = SimulatedTrade(
            trade_id="t2",
            symbol=w.spec.symbol,
            side="LONG",
            entry_timestamp=ts - timedelta(minutes=50),
            exit_timestamp=ts - timedelta(minutes=10),
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            exit_price=Decimal("95"),
            entry_notional=Decimal("100"),
            exit_notional=Decimal("95"),
            entry_fee=Decimal("0.05"),
            exit_fee=Decimal("0.05"),
            fees=Decimal("0.10"),
            slippage_cost=Decimal("0.02"),
            gross_pnl=Decimal("-5.00"),
            net_pnl=Decimal("-5.10"),
            exit_reason="stop_loss",
        )
        return TradeSimulationResult(
            symbol=w.spec.symbol,
            starting_equity=Decimal("100.00"),
            final_equity=Decimal("104.80"),
            total_fees=Decimal("0.20"),
            total_slippage_cost=Decimal("0.04"),
            equity_curve=(EquityPoint(timestamp=ts, equity=Decimal("104.80")),),
            trades=(t1, t2),
        )

    result = execute_autonomous_cycle(
        config=config,
        windows=(window,),
        prior_feedback=feedback,
        critic_transport=mock_critic_transport,
        creator_transport=mock_creator_transport,
        paper_engine=engine,
        simulator=_mock_winning_simulator,
        now=NOW,
    )

    assert result.cycle_status == "completed_admitted"
    assert result.candidate_id is not None
    assert result.candidate_id != initial_cand.candidate_id
    assert result.qualification_decision == "qualified"
    assert result.admission_decision == "admitted"
    assert engine.candidates["BTCUSDT"].candidate_id == result.candidate_id


def test_autonomous_cycle_rejected_qualification_preserves_active_candidate(tmp_path: Path):
    initial_cand = _build_test_candidate("cand-initial-001")
    window = _make_cached_window()

    feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash="1" * 64,
        qualification_policy_id="policy-cycle-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.5"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    def mock_critic_transport(req: LearnerCriticRequest) -> dict:
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier"],
        }

    def mock_creator_transport(req: CreatorGenerationRequest) -> dict:
        return {
            "proposal_id": "proposal-failed-003",
            "research_run_id": req.research_run_id,
            "hypothesis": "Revised strategy",
            "expected_regime": "trending",
            "novelty_reason": "Testing rejected path",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": "cand-revised-003",
                "family": "range_mean_reversion",
                "universe": {
                    "symbols": ["BTCUSDT"],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
                "entry": {"long": "rsi <= 10", "short": "rsi >= 90"},
                "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.1"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("4.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    # Impossible profit factor forces qualification failure
    config = AutonomousCycleConfig(
        cycle_id="cycle-002",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_policy=_policy(min_profit_factor="999.0"),
        artifact_root=tmp_path / "artifacts",
        max_attempts=1,
    )

    result = execute_autonomous_cycle(
        config=config,
        windows=(window,),
        prior_feedback=feedback,
        critic_transport=mock_critic_transport,
        creator_transport=mock_creator_transport,
        paper_engine=engine,
        now=NOW,
    )

    # Candidate was rejected, paper candidate remains untouched!
    assert result.cycle_status == "completed_unadmitted"
    assert result.qualification_decision == "rejected"
    assert result.admission_decision == "blocked_unqualified"
    assert engine.candidates["BTCUSDT"].candidate_id == initial_cand.candidate_id


def test_autonomous_cycle_critic_stop_halts_early(tmp_path: Path):
    initial_cand = _build_test_candidate("cand-initial-001")
    window = _make_cached_window()

    feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash="1" * 64,
        qualification_policy_id="policy-cycle-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.1"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    def mock_critic_stop_transport(req: LearnerCriticRequest) -> dict:
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "stop",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["no_further_viable_parameter_revisions"],
        }

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    config = AutonomousCycleConfig(
        cycle_id="cycle-003",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_policy=_policy(),
        artifact_root=tmp_path / "artifacts",
        max_attempts=1,
    )

    result = execute_autonomous_cycle(
        config=config,
        windows=(window,),
        prior_feedback=feedback,
        critic_transport=mock_critic_stop_transport,
        creator_transport=lambda _req: {},  # Should not be called
        paper_engine=engine,
        now=NOW,
    )

    assert result.cycle_status == "stopped"
    assert "critic_stopped_revision" in result.stop_reasons
    assert engine.candidates["BTCUSDT"].candidate_id == initial_cand.candidate_id


def test_autonomous_cycle_idempotency_and_repeat_execution(tmp_path: Path):
    initial_cand = _build_test_candidate("cand-initial-001", stop_atr="0.5")
    window = _make_cached_window()

    feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash="1" * 64,
        qualification_policy_id="policy-cycle-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.8"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    def mock_critic_transport(req: LearnerCriticRequest) -> dict:
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier"],
        }

    def mock_creator_transport(req: CreatorGenerationRequest) -> dict:
        return {
            "proposal_id": "proposal-revised-002",
            "research_run_id": req.research_run_id,
            "hypothesis": "Wider stop ATR accommodates volatility",
            "expected_regime": "trending",
            "novelty_reason": "Learner critique feedback incorporated",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": "cand-revised-002",
                "family": "range_mean_reversion",
                "universe": {
                    "symbols": ["BTCUSDT"],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
                "entry": {"long": "rsi <= 35", "short": "rsi >= 65"},
                "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.1"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("4.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    config = AutonomousCycleConfig(
        cycle_id="cycle-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_policy=_policy(min_profit_factor="0.0"),
        artifact_root=tmp_path / "artifacts",
        max_attempts=1,
    )

    def _mock_winning_simulator(c, frame, w):
        ts = frame["timestamp"].iloc[-1].to_pydatetime()
        t1 = SimulatedTrade(
            trade_id="t1",
            symbol=w.spec.symbol,
            side="LONG",
            entry_timestamp=ts - timedelta(hours=2),
            exit_timestamp=ts - timedelta(hours=1),
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            exit_price=Decimal("110"),
            entry_notional=Decimal("100"),
            exit_notional=Decimal("110"),
            entry_fee=Decimal("0.05"),
            exit_fee=Decimal("0.05"),
            fees=Decimal("0.10"),
            slippage_cost=Decimal("0.02"),
            gross_pnl=Decimal("10.00"),
            net_pnl=Decimal("9.90"),
            exit_reason="take_profit",
        )
        t2 = SimulatedTrade(
            trade_id="t2",
            symbol=w.spec.symbol,
            side="LONG",
            entry_timestamp=ts - timedelta(minutes=50),
            exit_timestamp=ts - timedelta(minutes=10),
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            exit_price=Decimal("95"),
            entry_notional=Decimal("100"),
            exit_notional=Decimal("95"),
            entry_fee=Decimal("0.05"),
            exit_fee=Decimal("0.05"),
            fees=Decimal("0.10"),
            slippage_cost=Decimal("0.02"),
            gross_pnl=Decimal("-5.00"),
            net_pnl=Decimal("-5.10"),
            exit_reason="stop_loss",
        )
        return TradeSimulationResult(
            symbol=w.spec.symbol,
            starting_equity=Decimal("100.00"),
            final_equity=Decimal("104.80"),
            total_fees=Decimal("0.20"),
            total_slippage_cost=Decimal("0.04"),
            equity_curve=(EquityPoint(timestamp=ts, equity=Decimal("104.80")),),
            trades=(t1, t2),
        )

    # First cycle execution
    result1 = execute_autonomous_cycle(
        config=config,
        windows=(window,),
        prior_feedback=feedback,
        critic_transport=mock_critic_transport,
        creator_transport=mock_creator_transport,
        paper_engine=engine,
        simulator=_mock_winning_simulator,
        now=NOW,
    )
    assert result1.cycle_status == "completed_admitted"
    assert engine.candidates["BTCUSDT"].candidate_id == result1.candidate_id

    # Second cycle execution (same config, same artifacts already written)
    result2 = execute_autonomous_cycle(
        config=config,
        windows=(window,),
        prior_feedback=feedback,
        critic_transport=mock_critic_transport,
        creator_transport=mock_creator_transport,
        paper_engine=engine,
        simulator=_mock_winning_simulator,
        now=NOW,
    )
    assert result2.cycle_status == "completed_admitted"
    assert result2.cycle_hash == result1.cycle_hash
    assert result2.candidate_artifact_hash == result1.candidate_artifact_hash
    assert result2.qualification_hash == result1.qualification_hash
    assert engine.candidates["BTCUSDT"].candidate_id == result1.candidate_id
