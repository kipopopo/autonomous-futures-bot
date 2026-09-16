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
from autonomous_futures.paper.observation import PaperObservation, PaperObservationBinding
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
        registry_manifest=DEFAULT_CANDIDATE_REGISTRY_PATH,
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


def test_live_paper_engine_resolves_symbols_dynamically_from_manifest(tmp_path: Path) -> None:
    """Engine dynamically resolves symbols from manifest v2 when symbols is not provided."""
    cand = _build_test_candidate("cand-test-avax", "AVAXUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"AVAXUSDT": (cand, qual)})

    # Initialize LivePaperEngine WITHOUT passing symbols
    engine = LivePaperEngine(
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    assert engine.symbols == ("AVAXUSDT",)
    assert "AVAXUSDT" in engine.candidates
    assert engine.candidates["AVAXUSDT"].candidate_id == "cand-test-avax"
    assert "AVAXUSDT" in engine.qualified_symbols
    assert engine.candidate_admission_decisions["AVAXUSDT"].decision == "admitted"


def test_discover_and_admit_candidates_runtime(tmp_path: Path) -> None:
    """discover_and_admit_candidates dynamically admits new candidate symbols at runtime."""
    cand_btc = _build_test_candidate("cand-btc", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_btc = _write_v2_manifest(tmp_path / "m1", {"BTCUSDT": (cand_btc, qual_btc)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_btc,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    assert "BTCUSDT" in engine.candidates

    # Discover and admit a new candidate for AVAXUSDT
    cand_avax = _build_test_candidate("cand-avax", "AVAXUSDT")
    qual_avax = _build_test_qualification(cand_avax, "qualified")
    manifest_avax = _write_v2_manifest(tmp_path / "m2", {"AVAXUSDT": (cand_avax, qual_avax)})

    decisions = engine.discover_and_admit_candidates(manifest_avax)
    assert "AVAXUSDT" in decisions
    assert decisions["AVAXUSDT"].decision == "admitted"
    assert "AVAXUSDT" in engine.candidates
    assert "AVAXUSDT" in engine.symbols
    assert "AVAXUSDT" in engine.qualified_symbols
    assert "AVAXUSDT" in engine._bar_history


def test_discover_and_admit_candidates_deferred_active_position(tmp_path: Path) -> None:
    """discover_and_admit_candidates defers admission when active trade is open."""
    from unittest.mock import MagicMock

    cand_btc = _build_test_candidate("cand-btc-001", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_btc = _write_v2_manifest(tmp_path / "m1", {"BTCUSDT": (cand_btc, qual_btc)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_btc,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    # Active trade is open on BTCUSDT
    engine.active_trades["BTCUSDT"] = MagicMock()

    # Attempt dynamic admission of updated candidate for BTCUSDT with require_flat=True
    cand_btc_v2 = _build_test_candidate("cand-btc-002", "BTCUSDT")
    qual_btc_v2 = _build_test_qualification(cand_btc_v2, "qualified")
    manifest_btc_v2 = _write_v2_manifest(tmp_path / "m2", {"BTCUSDT": (cand_btc_v2, qual_btc_v2)})

    decisions = engine.discover_and_admit_candidates(manifest_btc_v2, require_flat=True)
    assert "BTCUSDT" in decisions
    assert decisions["BTCUSDT"].decision == "deferred_active_position"
    assert "active_position_open" in decisions["BTCUSDT"].reason_codes
    # Original candidate is retained
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-btc-001"


def test_engine_rejects_corrupted_json_in_artifacts(tmp_path: Path) -> None:
    """Engine rejects manifest loading when candidate or qualification file is corrupted JSON."""
    cand = _build_test_candidate("cand-corrupt-json", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    # Corrupt candidate file with invalid JSON syntax
    cand_file = tmp_path / "candidates" / f"{cand.candidate_id}.json"
    cand_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(DomainViolation, match="invalid JSON/schema"):
        LivePaperTradingEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )


def test_cohort_cli_and_script_corrupt_database_error_handling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI and standalone script handle corrupted SQLite databases gracefully with exit code 2."""
    from autonomous_futures.paper.cohort_cli import main as cli_main
    from scripts.run_paper_readiness_snapshot import main as script_main

    corrupt_db = tmp_path / "corrupt.sqlite3"
    corrupt_db.write_text("NOT A VALID SQLITE DATABASE", encoding="utf-8")

    # Test cohort_cli
    cli_ret = cli_main(["--ledger-path", str(corrupt_db)])
    assert cli_ret == 2
    cli_out = capsys.readouterr().out
    cli_payload = json.loads(cli_out)
    assert cli_payload["status"] == "error"
    assert cli_payload["error_code"] == "invalid_input"

    # Test run_paper_readiness_snapshot script
    script_ret = script_main(["--ledger-db", str(corrupt_db)])
    assert script_ret == 2
    script_err = capsys.readouterr().err
    script_payload = json.loads(script_err)
    assert script_payload["status"] == "error"
    assert script_payload["error_code"] == "invalid_input"


def test_evaluate_paper_cohort_snapshot_multi_symbol_shared_candidate(tmp_path: Path) -> None:
    """Cohort readiness evaluation handles multiple symbols sharing the same candidate artifact."""
    from autonomous_futures.research.creator_artifacts import (
        CreatorCandidateArtifact,
        _artifact_content_hash,
    )

    cand = _build_test_candidate("cand-shared-alpha", "BTCUSDT")
    cand_dict = cand.model_dump()
    cand_dict["strategy"]["universe"]["symbols"] = ["BTCUSDT", "ETHUSDT"]
    cand_shared = CreatorCandidateArtifact.model_validate(cand_dict)
    cand_shared = cand_shared.model_copy(
        update={"artifact_hash": _artifact_content_hash(cand_shared)}
    )
    qual = _build_test_qualification(cand_shared, "qualified")

    manifest_path = _write_v2_manifest(
        tmp_path, {"BTCUSDT": (cand_shared, qual), "ETHUSDT": (cand_shared, qual)}
    )

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"
    out_dir = tmp_path / "reports_shared"

    obs_store = SqlitePaperObservations(obs_db)
    observations = _generate_healthy_observations(
        cand_shared.candidate_id, cand_shared.artifact_hash, days=7
    )
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

    # Both symbols have health reports
    assert "BTCUSDT" in health_reports
    assert "ETHUSDT" in health_reports
    assert health_reports["BTCUSDT"].health_status == "healthy"
    assert health_reports["ETHUSDT"].health_status == "healthy"
    # Cohort report is not blocked by duplicate bindings
    assert cohort_report.cohort_status == "ready_for_human_review"
    assert len(cohort_report.candidates) == 1
    assert cohort_report.candidates[0].candidate_id == cand_shared.candidate_id


def test_admit_candidate_registers_symbol_with_engine_and_monitor(tmp_path: Path) -> None:
    """admit_candidate dynamically registers new symbol across engine and monitor components."""
    cand_btc = _build_test_candidate("cand-btc", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_path = _write_v2_manifest(tmp_path / "m1", {"BTCUSDT": (cand_btc, qual_btc)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    assert engine.symbols == ("BTCUSDT",)
    assert "ETHUSDT" not in engine.symbols

    cand_eth = _build_test_candidate("cand-eth", "ETHUSDT")
    qual_eth = _build_test_qualification(cand_eth, "qualified")
    decision = engine.admit_candidate(cand_eth, qual_eth)

    assert decision.decision == "admitted"
    assert "ETHUSDT" in engine.symbols
    assert "ETHUSDT" in engine.qualified_symbols
    assert "ETHUSDT" in engine.candidates
    assert "ETHUSDT" in engine._bar_history
    assert "ETHUSDT" in engine.max_observed_spread_bps
    assert "ETHUSDT" in engine.monitor.symbols
    assert "ETHUSDT" in engine.monitor._baseline_atrs
    assert "ETHUSDT" in engine.telemetry.monitored_symbols
    assert "ETHUSDT" in engine.feed_client.symbols


def test_discover_and_admit_candidates_registers_symbol_with_monitor_and_feed(
    tmp_path: Path,
) -> None:
    """discover_and_admit_candidates registers dynamic symbols across monitor and feed client."""
    cand_btc = _build_test_candidate("cand-btc", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_btc = _write_v2_manifest(tmp_path / "m1", {"BTCUSDT": (cand_btc, qual_btc)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_btc,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    cand_sol = _build_test_candidate("cand-sol", "SOLUSDT")
    qual_sol = _build_test_qualification(cand_sol, "qualified")
    manifest_sol = _write_v2_manifest(tmp_path / "m2", {"SOLUSDT": (cand_sol, qual_sol)})

    engine.discover_and_admit_candidates(manifest_sol)

    assert "SOLUSDT" in engine.symbols
    assert "SOLUSDT" in engine.monitor.symbols
    assert "SOLUSDT" in engine.telemetry.monitored_symbols
    assert "SOLUSDT" in engine.feed_client.symbols


def test_live_paper_engine_skips_unselected_manifest_symbols(tmp_path: Path) -> None:
    """Engine initializes cleanly when caller restricts symbols, skipping unselected candidates."""
    from autonomous_futures.paper.candidate_registry import (
        CandidateRegistryManifest,
        compute_registry_hash,
    )

    cand_btc = _build_test_candidate("cand-btc", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand_btc, qual_btc)})
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["symbols"]["SOLUSDT"] = {
        "candidate_id": "cand-sol-missing",
        "candidate_artifact_hash": "0" * 64,
        "artifact_path": "candidates/non_existent.json",
        "qualification_hash": "0" * 64,
        "admitted_at": NOW.isoformat(),
    }
    raw_m = CandidateRegistryManifest.model_validate(manifest_data)
    manifest_obj = raw_m.model_copy(update={"registry_hash": compute_registry_hash(raw_m)})
    manifest_path.write_text(manifest_obj.model_dump_json(indent=2) + "\n", encoding="utf-8")

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    assert engine.symbols == ("BTCUSDT",)
    assert "BTCUSDT" in engine.candidates
    assert "SOLUSDT" not in engine.candidates


def test_evaluate_paper_cohort_snapshot_prefers_obs_store_over_default_manifest(
    tmp_path: Path,
) -> None:
    """Inspects distinct candidates from observations store before default manifest fallback."""
    obs_db = tmp_path / "paper-observations.sqlite3"
    obs_store = SqlitePaperObservations(obs_db)
    cand_custom = "cand-custom-isolated"
    cand_hash = "a" * 64

    obs = PaperObservation(
        candidate_id=cand_custom,
        candidate_artifact_hash=cand_hash,
        observed_at=datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC),
        equity=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        peak_equity=Decimal("100"),
        drawdown_pct=Decimal("0"),
        open_position_count=0,
        quote_exposure=Decimal("0"),
        cumulative_fees=Decimal("0"),
        cumulative_slippage=Decimal("0"),
        accounting_complete=True,
        reason_codes=("paper_observation_complete",),
    )
    obs_store.append(obs)

    health_reports, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=tmp_path / "paper-ledger.sqlite3",
        lifecycle_path=tmp_path / "paper-lifecycle.sqlite3",
        observations_path=obs_db,
    )

    assert cand_custom in health_reports
    assert len(cohort_report.candidates) == 1
    assert cohort_report.candidates[0].candidate_id == cand_custom


def test_evaluate_paper_cohort_snapshot_handles_corrupt_marked_at(tmp_path: Path) -> None:
    """evaluate_paper_cohort_snapshot handles malformed timestamps in marks gracefully."""
    import sqlite3

    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    conn = sqlite3.connect(lifecycle_db)
    conn.execute("CREATE TABLE paper_lifecycle_marks (marked_at TEXT)")
    conn.execute("INSERT INTO paper_lifecycle_marks VALUES ('corrupt-non-iso-timestamp')")
    conn.commit()
    conn.close()

    health_reports, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_path=tmp_path / "paper-ledger.sqlite3",
        lifecycle_path=lifecycle_db,
        observations_path=tmp_path / "paper-observations.sqlite3",
        expected_bindings=[
            PaperObservationBinding(candidate_id="cand-test", candidate_artifact_hash="b" * 64)
        ],
    )

    assert cohort_report.cohort_status == "not_ready"
    assert health_reports["cand-test"].health_status == "unavailable"


def test_evaluate_paper_cohort_snapshot_handles_microsecond_timestamps(tmp_path: Path) -> None:
    """Snapshot rounds up microseconds to whole seconds without false future-mark block."""
    obs_db = tmp_path / "paper-observations.sqlite3"
    obs_store = SqlitePaperObservations(obs_db)

    dt = datetime(2026, 9, 16, 12, 0, 0, 500000, tzinfo=UTC)
    obs = PaperObservation(
        candidate_id="cand-microsecond-test",
        candidate_artifact_hash="c" * 64,
        observed_at=dt,
        equity=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        peak_equity=Decimal("100"),
        drawdown_pct=Decimal("0"),
        open_position_count=0,
        quote_exposure=Decimal("0"),
        cumulative_fees=Decimal("0"),
        cumulative_slippage=Decimal("0"),
        accounting_complete=True,
        reason_codes=("paper_observation_complete",),
    )
    obs_store.append(obs)

    health_reports, _ = evaluate_paper_cohort_snapshot(
        ledger_path=tmp_path / "paper-ledger.sqlite3",
        lifecycle_path=tmp_path / "paper-lifecycle.sqlite3",
        observations_path=obs_db,
        expected_bindings=[
            PaperObservationBinding(
                candidate_id="cand-microsecond-test", candidate_artifact_hash="c" * 64
            )
        ],
    )

    h_rep = health_reports["cand-microsecond-test"]
    assert "paper_health_observation_binding_or_time_invalid" not in h_rep.reason_codes
    assert h_rep.health_status != "blocked"


def test_engine_validates_qualification_hash_before_signals_and_execution(tmp_path: Path) -> None:
    """Engine rejects signal evaluation and trade execution if qualification hash was tampered."""
    cand = _build_test_candidate("cand-tamper-qual", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path, {"BTCUSDT": (cand, qual)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    # Tamper with qualification in memory
    tampered_qual = engine.qualifications["BTCUSDT"].model_copy(
        update={"qualification_hash": "f" * 64}
    )
    engine.qualifications["BTCUSDT"] = tampered_qual

    # execute_open must reject the trade
    res = engine.execute_open(
        symbol="BTCUSDT",
        signal=1,
        conviction=Decimal("0.80"),
        event_time=datetime.now(UTC),
    )
    assert res is None
    assert "BTCUSDT" not in engine.active_trades


def test_live_paper_engine_restart_with_active_trade_enforces_require_flat(
    tmp_path: Path,
) -> None:
    """Engine restart with active position rejects admission when require_flat=True."""
    from autonomous_futures.feed.models import TickerSnapshot

    cand = _build_test_candidate("cand-btc-flat", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path / "m1", {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=obs_db,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("1"),
        transaction_time=datetime.now(UTC),
        event_time=datetime.now(UTC),
    )
    opened = engine.execute_open("BTCUSDT", 1, Decimal("0.8"), datetime.now(UTC))
    assert opened is not None
    engine._mark_active_position(
        engine.active_trades["BTCUSDT"],
        Decimal("50010"),
        datetime.now(UTC) + timedelta(seconds=10),
    )

    # Restarting engine with require_flat=True must fail with DomainViolation
    with pytest.raises(DomainViolation, match="admission blocked: deferred_active_position"):
        LivePaperEngine(
            symbols=("BTCUSDT",),
            registry_manifest=manifest_path,
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=obs_db,
            require_flat=True,
        )


def test_live_paper_engine_restart_with_active_trade_retained(tmp_path: Path) -> None:
    """Engine restart retains active position when require_flat=False."""
    from autonomous_futures.feed.models import TickerSnapshot

    cand = _build_test_candidate("cand-btc-retain", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path / "m2", {"BTCUSDT": (cand, qual)})

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=obs_db,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("1"),
        transaction_time=datetime.now(UTC),
        event_time=datetime.now(UTC),
    )
    opened = engine.execute_open("BTCUSDT", 1, Decimal("0.8"), datetime.now(UTC))
    assert opened is not None
    engine._mark_active_position(
        engine.active_trades["BTCUSDT"],
        Decimal("50010"),
        datetime.now(UTC) + timedelta(seconds=10),
    )

    # Restarting engine with require_flat=False must preserve active trade and update decision
    restarted = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=obs_db,
        require_flat=False,
    )
    assert "BTCUSDT" in restarted.active_trades
    dec = restarted.admission_decisions["BTCUSDT"]
    assert dec.decision == "admitted"
    assert dec.active_trade_retained is True
    assert "candidate_qualified_active_trade_retained" in dec.reason_codes


def test_admit_candidate_registers_qualification_and_checks_hash_integrity(
    tmp_path: Path,
) -> None:
    """admit_candidate registers qualification artifact and rejects execution if tampered."""
    from autonomous_futures.feed.models import TickerSnapshot

    cand_btc = _build_test_candidate("cand-btc-base", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    manifest_path = _write_v2_manifest(tmp_path / "m3", {"BTCUSDT": (cand_btc, qual_btc)})

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    cand_eth = _build_test_candidate("cand-eth-admit", "ETHUSDT")
    qual_eth = _build_test_qualification(cand_eth, "qualified")

    decision = engine.admit_candidate(cand_eth, qual_eth)
    assert decision.decision == "admitted"
    assert "ETHUSDT" in engine.qualifications
    assert engine.qualifications["ETHUSDT"].qualification_hash == qual_eth.qualification_hash

    # Tamper with ETH qualification in memory
    engine.qualifications["ETHUSDT"] = qual_eth.model_copy(update={"qualification_hash": "e" * 64})

    engine.latest_tickers["ETHUSDT"] = TickerSnapshot(
        symbol="ETHUSDT",
        best_bid_price=Decimal("3000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("3001"),
        best_ask_qty=Decimal("1"),
        transaction_time=datetime.now(UTC),
        event_time=datetime.now(UTC),
    )

    res = engine.execute_open("ETHUSDT", 1, Decimal("0.8"), datetime.now(UTC))
    assert res is None
    assert "ETHUSDT" not in engine.active_trades


def test_evaluate_cohort_readiness_excludes_unselected_manifest_symbols(
    tmp_path: Path,
) -> None:
    """evaluate_cohort_readiness only evaluates candidates admitted to the engine."""
    cand_btc = _build_test_candidate("cand-btc-single", "BTCUSDT")
    qual_btc = _build_test_qualification(cand_btc, "qualified")
    cand_sol = _build_test_candidate("cand-sol-unselected", "SOLUSDT")
    qual_sol = _build_test_qualification(cand_sol, "qualified")
    manifest_path = _write_v2_manifest(
        tmp_path / "m4",
        {"BTCUSDT": (cand_btc, qual_btc), "SOLUSDT": (cand_sol, qual_sol)},
    )

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        registry_manifest=manifest_path,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    health_reports, cohort_report = engine.evaluate_cohort_readiness()
    assert list(health_reports.keys()) == ["BTCUSDT"]
    assert cohort_report.expected_candidate_count == 1
    assert cohort_report.candidates[0].candidate_id == cand_btc.candidate_id


def test_evaluate_paper_cohort_snapshot_rejects_tampered_manifest_object(
    tmp_path: Path,
) -> None:
    """evaluate_paper_cohort_snapshot rejects tampered CandidateRegistryManifest object."""
    from autonomous_futures.paper.candidate_registry import (
        CandidateRegistryManifest,
    )

    cand = _build_test_candidate("cand-btc-obj", "BTCUSDT")
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(tmp_path / "m5", {"BTCUSDT": (cand, qual)})
    manifest_obj = CandidateRegistryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    tampered_manifest = manifest_obj.model_copy(update={"registry_hash": "f" * 64})

    with pytest.raises(DomainViolation, match="CandidateRegistryManifest registry_hash mismatch"):
        evaluate_paper_cohort_snapshot(
            ledger_path=tmp_path / "paper-ledger.sqlite3",
            lifecycle_path=tmp_path / "paper-lifecycle.sqlite3",
            observations_path=tmp_path / "paper-observations.sqlite3",
            manifest=tampered_manifest,
        )


def test_evaluate_paper_cohort_snapshot_scopes_active_marks_by_symbol(
    tmp_path: Path,
) -> None:
    """Active lifecycle marks are scoped to the matching symbol for shared candidates."""
    from autonomous_futures.feed.models import TickerSnapshot

    cand = _build_test_candidate("cand-shared-sym", "BTCUSDT")
    cand = cand.model_copy(
        update={
            "strategy": cand.strategy.model_copy(
                update={
                    "universe": cand.strategy.universe.model_copy(
                        update={"symbols": ("BTCUSDT", "ETHUSDT")}
                    )
                }
            )
        }
    )
    from autonomous_futures.research.creator_artifacts import _artifact_content_hash

    cand = cand.model_copy(update={"artifact_hash": _artifact_content_hash(cand)})
    qual = _build_test_qualification(cand, "qualified")
    manifest_path = _write_v2_manifest(
        tmp_path / "m6",
        {"BTCUSDT": (cand, qual), "ETHUSDT": (cand, qual)},
    )

    ledger_db = tmp_path / "paper-ledger.sqlite3"
    lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
    obs_db = tmp_path / "paper-observations.sqlite3"

    engine = LivePaperEngine(
        symbols=("BTCUSDT", "ETHUSDT"),
        registry_manifest=manifest_path,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=obs_db,
    )
    now = datetime.now(UTC)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("1"),
        transaction_time=now,
        event_time=now,
    )
    engine.latest_tickers["ETHUSDT"] = TickerSnapshot(
        symbol="ETHUSDT",
        best_bid_price=Decimal("3000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("3001"),
        best_ask_qty=Decimal("1"),
        transaction_time=now,
        event_time=now,
    )

    op_btc = engine.execute_open("BTCUSDT", 1, Decimal("0.8"), now)
    op_eth = engine.execute_open("ETHUSDT", 1, Decimal("0.8"), now)
    assert op_btc is not None and op_eth is not None

    engine._mark_active_position(
        engine.active_trades["BTCUSDT"], Decimal("50010"), now + timedelta(seconds=60)
    )
    engine._mark_active_position(
        engine.active_trades["ETHUSDT"], Decimal("3005"), now + timedelta(seconds=60)
    )

    from autonomous_futures.paper.observation import PaperObservation
    from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations

    obs_store = SqlitePaperObservations(obs_db)
    obs = PaperObservation(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        observed_at=now,
        equity=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        peak_equity=Decimal("100"),
        drawdown_pct=Decimal("0"),
        open_position_count=2,
        quote_exposure=Decimal("6000"),
        cumulative_fees=Decimal("0"),
        cumulative_slippage=Decimal("0"),
        accounting_complete=True,
        reason_codes=("paper_observation_complete",),
    )
    obs_store.append(obs)

    health_reports, _ = evaluate_paper_cohort_snapshot(
        ledger_path=ledger_db,
        lifecycle_path=lifecycle_db,
        observations_path=obs_db,
        manifest=manifest_path,
    )

    btc_health = health_reports["BTCUSDT"]
    eth_health = health_reports["ETHUSDT"]

    assert len(btc_health.lifecycle) == 1
    assert btc_health.lifecycle[0].trade_id == op_btc.trade_id
    assert btc_health.lifecycle[0].symbol == "BTCUSDT"

    assert len(eth_health.lifecycle) == 1
    assert eth_health.lifecycle[0].trade_id == op_eth.trade_id
    assert eth_health.lifecycle[0].symbol == "ETHUSDT"


def test_evaluate_paper_cohort_snapshot_persists_report_on_empty_db(tmp_path: Path) -> None:
    """evaluate_paper_cohort_snapshot persists readiness report even when empty."""
    from autonomous_futures.paper.candidate_registry import (
        CandidateRegistryManifest,
        compute_registry_hash,
    )

    # 1. Fallback to default repo manifest against empty DBs writes report (status not_ready)
    out_dir1 = tmp_path / "reports_empty_db"
    health_reports1, cohort_report1 = evaluate_paper_cohort_snapshot(
        ledger_path=tmp_path / "empty-ledger.sqlite3",
        lifecycle_path=tmp_path / "empty-lifecycle.sqlite3",
        observations_path=tmp_path / "empty-observations.sqlite3",
        output_dir=out_dir1,
    )
    assert cohort_report1.cohort_status == "not_ready"
    assert (out_dir1 / "paper-cohort-readiness-report.json").is_file()

    # 2. Fully empty manifest with zero candidate entries writes report (status unavailable)
    out_dir2 = tmp_path / "reports_empty_manifest"
    raw_m = CandidateRegistryManifest(
        registry_version=2,
        symbols={},
        updated_at=datetime.now(UTC).isoformat(),
        registry_hash="0" * 64,
    )
    empty_manifest = raw_m.model_copy(update={"registry_hash": compute_registry_hash(raw_m)})
    health_reports2, cohort_report2 = evaluate_paper_cohort_snapshot(
        ledger_path=tmp_path / "empty-ledger.sqlite3",
        lifecycle_path=tmp_path / "empty-lifecycle.sqlite3",
        observations_path=tmp_path / "empty-observations.sqlite3",
        manifest=empty_manifest,
        output_dir=out_dir2,
    )
    assert cohort_report2.cohort_status == "unavailable"
    assert (out_dir2 / "paper-cohort-readiness-report.json").is_file()
    saved_report = json.loads(
        (out_dir2 / "paper-cohort-readiness-report.json").read_text(encoding="utf-8")
    )
    assert saved_report["cohort_status"] == "unavailable"


def test_scripts_and_cli_support_expected_path(tmp_path: Path, capsys) -> None:
    """scripts/run_paper_readiness_snapshot.py and cohort_cli.py support --expected-path."""
    from autonomous_futures.paper.cohort_cli import main as cli_main
    from scripts.run_paper_readiness_snapshot import main as script_main

    bindings = [
        {
            "candidate_id": "cand-exp-cli",
            "candidate_artifact_hash": "d" * 64,
        }
    ]
    exp_path = tmp_path / "expected_bindings.json"
    exp_path.write_text(json.dumps(bindings), encoding="utf-8")

    out_script = tmp_path / "out_script"
    rc_script = script_main(
        [
            "--ledger-path",
            str(tmp_path / "paper-ledger.sqlite3"),
            "--lifecycle-path",
            str(tmp_path / "paper-lifecycle.sqlite3"),
            "--observations-path",
            str(tmp_path / "paper-observations.sqlite3"),
            "--expected-path",
            str(exp_path),
            "--output-dir",
            str(out_script),
        ]
    )
    assert rc_script == 0
    payload_script = json.loads(capsys.readouterr().out)
    assert payload_script["status"] == "not_ready"
    assert payload_script["expected_candidate_count"] == 1

    rc_cli = cli_main(
        [
            "--ledger-path",
            str(tmp_path / "paper-ledger.sqlite3"),
            "--lifecycle-path",
            str(tmp_path / "paper-lifecycle.sqlite3"),
            "--observations-path",
            str(tmp_path / "paper-observations.sqlite3"),
            "--expected-path",
            str(exp_path),
        ]
    )
    assert rc_cli == 0
    payload_cli = json.loads(capsys.readouterr().out)
    assert payload_cli["status"] == "not_ready"
    assert payload_cli["expected_candidate_count"] == 1
