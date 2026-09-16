"""Targeted unit tests for candidate manifest v2 discovery, dynamic admission,
single-position invariants, cohort readiness evaluation, and fail-closed runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper import (
    LivePaperEngine,
    LivePaperTradingEngine,
    evaluate_paper_cohort_snapshot,
)
from autonomous_futures.paper.candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateManifestEntry,
    build_candidate_registry_manifest,
)
from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationGateResult,
    QualificationMetric,
    _qualification_content_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _build_test_candidate(
    candidate_id: str = "cand-test-001",
    symbol: str = "BTCUSDT",
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="run-test-creator-001",
        research_seed=42,
        created_at=NOW,
    )


def _build_test_qualification(
    candidate: CreatorCandidateArtifact,
    decision: str = "qualified",
) -> CreatorCandidateQualificationArtifact:
    gates = (
        QualificationGateResult(
            gate_id="oos_profit_factor_min",
            passed=decision == "qualified",
            observed=Decimal("1.5"),
            threshold=Decimal("1.0"),
            comparator="gte",
            reason_code=(
                "oos_profit_factor_acceptable"
                if decision == "qualified"
                else "oos_profit_factor_below_threshold"
            ),
        ),
    )
    metrics = (QualificationMetric(metric_id="profit_factor", value=Decimal("1.5")),)
    provisional = CreatorCandidateQualificationArtifact.model_validate(
        {
            "qualification_version": 1,
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_hash": candidate.artifact_hash,
            "bundle_hash": candidate.bundle_hash,
            "dataset_registry_hash": candidate.dataset_registry_hash,
            "evaluator_run_id": "run-test-eval-001",
            "evaluator_version": "1.0.0",
            "decision": decision,
            "metrics": metrics,
            "gates": gates,
            "windows_evaluated": 5,
            "qualification_policy_id": "policy-test-001",
            "oos_aggregation_hash": "d" * 64,
            "source": "walk_forward_oos",
            "evaluated_at": NOW,
            "promotion_state": "unpromoted",
            "execution_authority": False,
            "qualification_hash": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def _write_v2_manifest(
    tmp_path: Path,
    candidates: dict[str, tuple[CreatorCandidateArtifact, CreatorCandidateQualificationArtifact]],
    version: int = 2,
    corrupt_registry_hash: bool = False,
) -> Path:
    candidates_dir = tmp_path / "candidates"
    qualifications_dir = tmp_path / "qualifications"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    qualifications_dir.mkdir(parents=True, exist_ok=True)

    symbols_map: dict[str, CandidateManifestEntry] = {}
    for sym, (cand, qual) in candidates.items():
        cand_path = candidates_dir / f"{cand.candidate_id}.json"
        cand_path.write_text(cand.model_dump_json(indent=2) + "\n", encoding="utf-8")
        qual_path = qualifications_dir / f"qual-{cand.candidate_id}.json"
        qual_path.write_text(qual.model_dump_json(indent=2) + "\n", encoding="utf-8")
        qual_path2 = qualifications_dir / f"{cand.candidate_id}.json"
        qual_path2.write_text(qual.model_dump_json(indent=2) + "\n", encoding="utf-8")

        symbols_map[sym] = CandidateManifestEntry(
            candidate_id=cand.candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=f"candidates/{cand.candidate_id}.json",
            qualification_hash=qual.qualification_hash,
            admitted_at=NOW.isoformat(),
        )

    manifest = build_candidate_registry_manifest(
        symbols=symbols_map,
        updated_at=NOW,
        registry_version=version,
    )
    if corrupt_registry_hash:
        manifest = manifest.model_copy(update={"registry_hash": "f" * 64})
    manifest_path = tmp_path / "candidate_registry.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _generate_healthy_observations(
    candidate_id: str,
    candidate_hash: str,
    days: int = 7,
) -> list[PaperObservation]:
    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = []
    for index in range(days * 4):
        observations.append(
            PaperObservation(
                candidate_id=candidate_id,
                candidate_artifact_hash=candidate_hash,
                observed_at=first + timedelta(hours=6 * index),
                equity=Decimal("100"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                peak_equity=Decimal("100"),
                drawdown_pct=Decimal("0"),
                open_position_count=0,
                quote_exposure=Decimal("0"),
                cumulative_fees=Decimal("0.01"),
                cumulative_slippage=Decimal("0.005"),
                accounting_complete=True,
                reason_codes=("paper_observation_complete",),
            )
        )
    return observations


# =========================================================================
# Tests: Manifest v2 Discovery & Dynamic Admission (R1)
# =========================================================================


def test_live_paper_trading_engine_alias() -> None:
    """Verify LivePaperTradingEngine is an exported alias for LivePaperEngine."""
    assert LivePaperTradingEngine is LivePaperEngine


def test_live_paper_engine_loads_repo_v2_manifest(tmp_path: Path) -> None:
    """LivePaperEngine loads artifacts/paper_live/candidate_registry.json cleanly."""
    if not Path(DEFAULT_CANDIDATE_REGISTRY_PATH).is_file():
        pytest.skip("Default candidate registry file not found in checkout.")

    engine = LivePaperEngine(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    assert engine.registry_manifest is not None
    assert engine.registry_manifest.registry_version >= 2
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in engine.candidates
        assert sym in engine.candidate_admission_decisions
        assert engine.candidate_admission_decisions[sym].decision == "admitted"
        assert sym in engine.qualifications


def test_live_paper_engine_loads_custom_v2_manifest(tmp_path: Path) -> None:
    """Engine discovers and admits candidate from custom v2 manifest."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    engine = LivePaperTradingEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    assert "BTCUSDT" in engine.candidates
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-test-alpha"
    assert engine.candidate_admission_decisions["BTCUSDT"].decision == "admitted"
    assert (
        engine.candidate_admission_decisions["BTCUSDT"].qualification_hash
        == qual.qualification_hash
    )
    assert engine.qualifications["BTCUSDT"].qualification_hash == qual.qualification_hash


def test_engine_rejects_manifest_version_less_than_two(tmp_path: Path) -> None:
    """Engine rejects candidate registry manifest with version < 2."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)}, version=1)

    with pytest.raises(ValueError, match=r"(?i)manifest version must be >= 2"):
        LivePaperTradingEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )


def test_engine_rejects_tampered_manifest_registry_hash(tmp_path: Path) -> None:
    """Engine rejects manifest when registry_hash is tampered."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(
        tmp_path, {"BTCUSDT": (cand, qual)}, corrupt_registry_hash=True
    )

    with pytest.raises(DomainViolation, match="hash mismatch"):
        LivePaperTradingEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )


def test_engine_rejects_tampered_candidate_artifact(tmp_path: Path) -> None:
    """Engine rejects manifest when candidate artifact JSON does not match hash."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    # Tamper with candidate file
    cand_file = tmp_path / "candidates" / f"{cand.candidate_id}.json"
    cand_data = json.loads(cand_file.read_text(encoding="utf-8"))
    cand_data["bundle_hash"] = "0" * 64
    cand_file.write_text(json.dumps(cand_data), encoding="utf-8")

    with pytest.raises(DomainViolation, match="artifact hash mismatch"):
        LivePaperTradingEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )


def test_engine_rejects_tampered_qualification_artifact(tmp_path: Path) -> None:
    """Engine rejects manifest when candidate qualification artifact does not match hash."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    # Tamper with qualification files
    for q_name in (f"qual-{cand.candidate_id}.json", f"{cand.candidate_id}.json"):
        qual_file = tmp_path / "qualifications" / q_name
        if qual_file.is_file():
            qual_data = json.loads(qual_file.read_text(encoding="utf-8"))
            qual_data["decision"] = "rejected"
            qual_file.write_text(json.dumps(qual_data), encoding="utf-8")

    with pytest.raises(DomainViolation, match=r"(?i)qualification.*hash mismatch"):
        LivePaperTradingEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )


def test_single_position_invariant_prevents_concurrent_positions(tmp_path: Path) -> None:
    """Engine maintains single-position invariant per symbol."""
    from unittest.mock import MagicMock

    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    # Place an active trade mock in active_trades
    engine.active_trades["BTCUSDT"] = MagicMock()

    # Attempting to execute open should be rejected (returns None) due to single-position invariant
    result = engine.execute_open("BTCUSDT", 1, Decimal("1.0"), NOW)
    assert result is None


# =========================================================================
# Tests: Automated Cohort Readiness Evaluation (R2 & R3)
# =========================================================================


def test_evaluate_paper_cohort_snapshot_ready_for_human_review(tmp_path: Path) -> None:
    """Cohort readiness evaluation reports ready_for_human_review when all symbols are healthy."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"
    out_dir = tmp_path / "reports"

    # Populate 7 days of observations
    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(cand.candidate_id, cand.artifact_hash, days=7)
    for obs in observations:
        obs_store.append(obs)

    as_of = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=7)

    health_reports, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=ledger_db,
        lifecycle_path=lifecycle_db,
        observations_path=obs_db,
        manifest=manifest_path,
        output_dir=out_dir,
        as_of=as_of,
        required_days=7,
    )

    assert "BTCUSDT" in health_reports
    assert health_reports["BTCUSDT"].health_status == "healthy"
    assert health_reports["BTCUSDT"].maturity_status == "mature"
    assert cohort_report.cohort_status == "ready_for_human_review"
    assert cohort_report.paper_activation is False
    assert cohort_report.execution_authority is False
    assert cohort_report.exchange_access is False

    # Check written report files
    report_file = out_dir / "paper-cohort-readiness-report.json"
    assert report_file.is_file()
    saved_cohort = json.loads(report_file.read_text(encoding="utf-8"))
    assert saved_cohort["cohort_status"] == "ready_for_human_review"
    assert saved_cohort["paper_activation"] is False

    symbol_report_file = out_dir / "paper-health-report-BTCUSDT.json"
    assert symbol_report_file.is_file()
    saved_symbol = json.loads(symbol_report_file.read_text(encoding="utf-8"))
    assert saved_symbol["health_status"] == "healthy"


def test_evaluate_paper_cohort_snapshot_not_ready_on_short_history(tmp_path: Path) -> None:
    """Cohort readiness evaluation reports not_ready when history is shorter than required_days."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(cand.candidate_id, cand.artifact_hash, days=2)
    for obs in observations:
        obs_store.append(obs)

    as_of = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=2)

    _, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=ledger_db,
        lifecycle_path=lifecycle_db,
        observations_path=obs_db,
        manifest=manifest_path,
        as_of=as_of,
        required_days=7,
    )

    assert cohort_report.cohort_status == "not_ready"
    assert cohort_report.all_mature is False


def test_evaluate_paper_cohort_snapshot_unavailable_on_missing_data(tmp_path: Path) -> None:
    """Cohort readiness evaluation reports unavailable when observation store is empty."""
    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    _, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=ledger_db,
        lifecycle_path=lifecycle_db,
        observations_path=obs_db,
        candidates={},
    )

    assert cohort_report.cohort_status == "unavailable"


def test_evaluate_paper_cohort_snapshot_blocked_on_blocked_candidate(tmp_path: Path) -> None:
    """Cohort readiness evaluation reports blocked when any candidate has blocked health."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(cand.candidate_id, cand.artifact_hash, days=7)
    blocked_obs = observations[-1].model_copy(
        update={
            "accounting_complete": False,
            "reason_codes": ("paper_halt_drawdown_limit_exceeded",),
        }
    )
    for obs in observations[:-1]:
        obs_store.append(obs)
    obs_store.append(blocked_obs)

    as_of = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=7)

    health_reports, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=ledger_db,
        lifecycle_path=lifecycle_db,
        observations_path=obs_db,
        manifest=manifest_path,
        as_of=as_of,
        required_days=7,
    )

    assert health_reports["BTCUSDT"].health_status == "blocked"
    assert cohort_report.cohort_status == "blocked"


def test_zero_secret_leakage_assertion() -> None:
    """Writing cohort reports fails closed with DomainViolation if a secret is detected."""
    from autonomous_futures.paper.cohort import _assert_zero_secrets

    with pytest.raises(DomainViolation, match="Secret pattern matched"):
        _assert_zero_secrets("key=AIzaSyA1234567890123456789012345678901", "test-report")

    with pytest.raises(DomainViolation, match="Secret pattern matched"):
        _assert_zero_secrets("authorization: Bearer secret-token-xyz1234567890", "test-report")


def test_live_paper_engine_cohort_readiness_method(tmp_path: Path) -> None:
    """LivePaperEngine.evaluate_cohort_readiness integrates cleanly with engine instances."""
    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    engine = LivePaperTradingEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    # Empty observations -> candidate reported as unavailable, cohort not_ready
    healths, cohort = engine.evaluate_cohort_readiness()
    assert cohort.cohort_status == "not_ready"
    assert cohort.paper_activation is False
    assert healths["BTCUSDT"].health_status == "unavailable"


# =========================================================================
# Tests: CLI Integration
# =========================================================================


def test_cohort_cli_sqlite_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """cohort_cli operates correctly in SQLite snapshot evaluation mode."""
    from autonomous_futures.paper.cohort_cli import main

    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"
    out_dir = tmp_path / "cli_reports"

    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(cand.candidate_id, cand.artifact_hash, days=7)
    for obs in observations:
        obs_store.append(obs)

    as_of = (datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=7)).isoformat()

    ret = main(
        [
            "--ledger-path",
            str(ledger_db),
            "--lifecycle-path",
            str(lifecycle_db),
            "--observations-path",
            str(obs_db),
            "--manifest-path",
            str(manifest_path),
            "--output-dir",
            str(out_dir),
            "--as-of",
            as_of,
            "--required-days",
            "7",
        ]
    )

    assert ret == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "ready_for_human_review"
    assert payload["paper_activation"] is False
    assert (out_dir / "paper-cohort-readiness-report.json").is_file()


def test_run_paper_readiness_snapshot_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """scripts/run_paper_readiness_snapshot.py executes cleanly."""
    import sys

    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from scripts.run_paper_readiness_snapshot import main

    cand = _build_test_candidate("cand-test-alpha", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"
    out_dir = tmp_path / "script_reports"

    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(cand.candidate_id, cand.artifact_hash, days=7)
    for obs in observations:
        obs_store.append(obs)

    as_of = (datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=7)).isoformat()

    ret = main(
        [
            "--ledger-path",
            str(ledger_db),
            "--lifecycle-path",
            str(lifecycle_db),
            "--observations-path",
            str(obs_db),
            "--manifest-path",
            str(manifest_path),
            "--output-dir",
            str(out_dir),
            "--as-of",
            as_of,
            "--required-days",
            "7",
        ]
    )

    assert ret == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "ready_for_human_review"
    assert (out_dir / "paper-cohort-readiness-report.json").is_file()
