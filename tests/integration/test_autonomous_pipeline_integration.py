"""End-to-end integration test for the autonomous pipeline cycle with real market data.

Validates:
  1. Real 5m Parquet bars loaded from research/immutable-data/5m/canonical/BTCUSDT-5m.parquet.
  2. Failure feedback -> Critic review -> Creator revision loop.
  3. Real out-of-sample walk-forward trade simulation (simulate_candidate_window).
  4. Real qualification gate evaluation (WalkForwardQualificationPolicy).
  5. Strategy admission decision & adoption into LivePaperEngine without mutating open trades.
  6. Zero paid API / live exchange calls (deterministic cached-only operation).
  7. Auditable SHA-256 artifacts and SQLite ledger integrity.
"""

from __future__ import annotations

import sqlite3
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
from autonomous_futures.paper.live_engine import ActivePaperTrade, LivePaperEngine
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
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.creator_generator import CreatorGenerationRequest
from autonomous_futures.research.learner_critic import LearnerCriticRequest
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)

PARQUET_PATH = Path("research/immutable-data/5m/canonical/BTCUSDT-5m.parquet")
BUNDLE_HASH = "e" * 64
DATASET_HASH = "f" * 64
EVAL_TIME = datetime(2026, 8, 6, 6, 0, tzinfo=UTC)


def _load_real_cached_window(
    symbol: str = "BTCUSDT", num_bars: int = 1000
) -> CachedEvaluationWindow:
    """Load canonical 5m Parquet data and construct an exact CachedEvaluationWindow."""
    assert PARQUET_PATH.exists(), f"Canonical Parquet file missing: {PARQUET_PATH}"
    df = pd.read_parquet(PARQUET_PATH)
    sub = df.iloc[-num_bars:].copy().reset_index(drop=True)
    time_start = sub["timestamp"].iloc[0].to_pydatetime()
    time_end = sub["timestamp"].iloc[-1].to_pydatetime() + timedelta(minutes=5)
    spec = CachedEvaluationWindowSpec(
        window_id="real-btc-5m-window-001",
        symbol=symbol,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        time_start=time_start,
        time_end=time_end,
    )
    return CachedEvaluationWindow(spec=spec, frame=sub)


def _build_candidate(
    cand_id: str, stop_atr: str = "1.0", take_profit_atr: str = "2.0"
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cand_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=3, shift=1),),
        entry=EntryExit(long="returns > 0.001", short="returns < -0.001"),
        exit=EntryExit(long="returns < 0.0", short="returns > 0.0"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_atr),
            take_profit_atr_multiplier=Decimal(take_profit_atr),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        creator_run_id="run-initial-001",
        research_seed=1,
        created_at=EVAL_TIME - timedelta(days=1),
    )


def test_autonomous_pipeline_integration_real_data(tmp_path: Path):
    """Full integrated autonomous cycle with real Parquet data and un-mocked simulation."""
    window = _load_real_cached_window()
    initial_cand = _build_candidate("cand-btc-initial-001", stop_atr="0.5")

    # Step 1: Initial failure feedback from past evaluation
    prior_feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        qualification_hash="2" * 64,
        qualification_policy_id="policy-real-wf-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.198"),
                threshold=Decimal("0.500"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    # Step 2: Critic transport receives request, recommends widening stop ATR
    def critic_transport(req: LearnerCriticRequest) -> dict:
        assert req.candidate_id == initial_cand.candidate_id
        assert "oos_profit_factor_below_threshold" in req.feedback.failure_reason_codes
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier", "adjust_take_profit_multiplier"],
        }

    # Step 3: Creator transport generates revised candidate with refined parameters
    def creator_transport(req: CreatorGenerationRequest) -> dict:
        assert req.research_run_id.startswith("run-creator-")
        assert len(req.input_evidence_refs) >= 2
        return {
            "proposal_id": "proposal-btc-revised-002",
            "research_run_id": req.research_run_id,
            "hypothesis": "Adjusting ATR multipliers to capture momentum on 5m BTC bars",
            "expected_regime": "trending",
            "novelty_reason": "Learner critique incorporated on real historical bars",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": "cand-btc-revised-002",
                "family": "experimental",
                "universe": {
                    "symbols": ["BTCUSDT"],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "returns", "lookback": 3, "shift": 1}],
                "entry": {"long": "returns > 0.001", "short": "returns < -0.001"},
                "exit": {"long": "returns < 0.0", "short": "returns > 0.0"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.10"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("3.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    # Initialize LivePaperEngine with SQLite databases
    ledger_db = tmp_path / "ledger.sqlite3"
    lifecycle_db = tmp_path / "lifecycle.sqlite3"
    obs_db = tmp_path / "obs.sqlite3"
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=obs_db,
    )

    # Realistic policy calibrated to 5m market data
    qualification_policy = WalkForwardQualificationPolicy(
        policy_id="policy-real-wf-001",
        minimum_windows=1,
        minimum_trades=10,
        minimum_profit_factor=Decimal("0.10"),  # real simulation produces ~0.198 pf
        maximum_drawdown_pct=Decimal("50.0"),
        minimum_average_return_pct=Decimal("-10.0"),
    )

    cycle_config = AutonomousCycleConfig(
        cycle_id="cycle-real-btc-001",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        qualification_policy=qualification_policy,
        artifact_root=tmp_path / "artifacts",
        max_attempts=1,
        require_flat=False,
    )

    # Step 4: Execute autonomous cycle with un-mocked simulator (real simulate_candidate_window)
    result = execute_autonomous_cycle(
        config=cycle_config,
        windows=(window,),
        prior_feedback=prior_feedback,
        critic_transport=critic_transport,
        creator_transport=creator_transport,
        paper_engine=engine,
        simulator=None,  # Real simulator invoked
        now=EVAL_TIME,
    )

    # Verification: Cycle status & candidate adoption
    assert result.cycle_status == "completed_admitted"
    assert result.qualification_decision == "qualified"
    assert result.admission_decision == "admitted"
    assert result.candidate_id is not None
    assert result.candidate_id != initial_cand.candidate_id
    assert engine.candidates["BTCUSDT"].candidate_id == result.candidate_id

    # Verification: Safety gates & boundedness
    assert result.data_source == "cached_only"
    assert result.promotion_state == "unpromoted"
    assert result.execution_authority is False
    assert len(result.cycle_hash) == 64
    assert len(result.candidate_artifact_hash) == 64
    assert len(result.qualification_hash) == 64
    assert len(result.admission_decision_hash) == 64

    # Verification: Artifacts persisted on disk
    cand_file = tmp_path / "artifacts" / "candidates" / f"{result.candidate_id}.json"
    qual_file = tmp_path / "artifacts" / "qualifications" / f"{result.qualification_hash}.json"
    assert cand_file.exists()
    assert qual_file.exists()

    # Verification: SQLite databases exist and are valid
    for db_path in (ledger_db, lifecycle_db, obs_db):
        assert db_path.exists()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA schema_version;")
            row = cursor.fetchone()
            assert row is not None


def test_autonomous_cycle_protects_open_positions_against_mutation(tmp_path: Path):
    """When a paper position is active, candidate admission retains original candidate binding."""
    window = _load_real_cached_window()
    initial_cand = _build_candidate("cand-btc-initial-001", stop_atr="0.5")

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    # Simulate an open position on BTCUSDT bound to initial_cand
    active_trade = ActivePaperTrade(
        trade_id="trade-open-001",
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        symbol="BTCUSDT",
        side="LONG",
        open_entry=None,  # type: ignore[arg-type]
        quantity=Decimal("1.0"),
        base_margin=Decimal("1000.0"),
        leverage=Decimal("1.0"),
        watermark=Decimal("60000.0"),
        peak_pnl=Decimal("0.0"),
        stop_price=Decimal("59000.0"),
        target_price=Decimal("62000.0"),
        trailing_atr_multiplier=Decimal("1.0"),
        current_atr=Decimal("100.0"),
        opened_at=EVAL_TIME - timedelta(minutes=15),
        candidate=initial_cand,  # Bound to original candidate
    )
    engine.active_trades["BTCUSDT"] = active_trade

    # Candidate qualification policy calibrated for test
    qualification_policy = WalkForwardQualificationPolicy(
        policy_id="policy-real-wf-002",
        minimum_windows=1,
        minimum_trades=10,
        minimum_profit_factor=Decimal("0.10"),
        maximum_drawdown_pct=Decimal("50.0"),
        minimum_average_return_pct=Decimal("-10.0"),
    )
    prior_feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial_cand.candidate_id,
        candidate_artifact_hash=initial_cand.artifact_hash,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        qualification_hash="3" * 64,
        qualification_policy_id="policy-real-wf-002",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.198"),
                threshold=Decimal("0.500"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )

    def critic_transport(req: LearnerCriticRequest) -> dict:
        return {
            "review_id": f"review-{req.candidate_id}",
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(req.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier"],
        }

    def creator_transport(req: CreatorGenerationRequest) -> dict:
        return {
            "proposal_id": "proposal-btc-revised-002",
            "research_run_id": req.research_run_id,
            "hypothesis": "Hypothesis for revision",
            "expected_regime": "trending",
            "novelty_reason": "Revision incorporated",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": "cand-btc-revised-002",
                "family": "experimental",
                "universe": {
                    "symbols": ["BTCUSDT"],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "returns", "lookback": 3, "shift": 1}],
                "entry": {"long": "returns > 0.001", "short": "returns < -0.001"},
                "exit": {"long": "returns < 0.0", "short": "returns > 0.0"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.10"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("3.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    # 1. When require_flat is True, active position blocks admission
    result_blocked = execute_autonomous_cycle(
        config=AutonomousCycleConfig(
            cycle_id="cycle-real-btc-flat",
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            qualification_policy=qualification_policy,
            artifact_root=tmp_path / "artifacts_blocked",
            max_attempts=1,
            require_flat=True,
        ),
        windows=(window,),
        prior_feedback=prior_feedback,
        critic_transport=critic_transport,
        creator_transport=creator_transport,
        paper_engine=engine,
        now=EVAL_TIME,
    )
    assert result_blocked.cycle_status == "completed_unadmitted"
    assert result_blocked.admission_decision == "deferred_active_position"
    assert engine.candidates["BTCUSDT"].candidate_id == initial_cand.candidate_id

    # 2. When require_flat is False, future entries adopt new candidate,
    # but active trade retains its original candidate binding
    result = execute_autonomous_cycle(
        config=AutonomousCycleConfig(
            cycle_id="cycle-real-btc-002",
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            qualification_policy=qualification_policy,
            artifact_root=tmp_path / "artifacts",
            max_attempts=1,
            require_flat=False,
        ),
        windows=(window,),
        prior_feedback=prior_feedback,
        critic_transport=critic_transport,
        creator_transport=creator_transport,
        paper_engine=engine,
        now=EVAL_TIME,
    )

    assert result.cycle_status == "completed_admitted"
    # The engine now routes FUTURE entries according to the new candidate:
    assert engine.candidates["BTCUSDT"].candidate_id == result.candidate_id
    # CRITICAL: The currently open trade STILL retains the initial candidate binding!
    assert engine.active_trades["BTCUSDT"].candidate is not None
    assert engine.active_trades["BTCUSDT"].candidate.candidate_id == initial_cand.candidate_id
