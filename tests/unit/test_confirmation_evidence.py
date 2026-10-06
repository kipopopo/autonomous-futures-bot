"""Synthetic cross-scope observations, not untouched holdout or acceptance proof."""

import json
import os
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.confirmation_evidence import (
    read_confirmation_window_evidence,
    write_confirmation_window_evidence,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    _qualification_content_hash,
    build_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import EquityPoint, TradeSimulationConfig
from autonomous_futures.research.window_evidence import (
    _content_hash,
    read_window_simulation_evidence,
    write_window_simulation_evidence,
)
from tests.unit.test_autonomous_cycle import _build_test_candidate, _make_cached_window
from tests.unit.test_cached_oos_walk_forward import _flat_result


def _inputs():
    candidate = _build_test_candidate("cand-confirmation-observation")
    qualification = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="synthetic-source-research",
        evaluator_version="synthetic-only",
        decision="qualified",
        metrics=(QualificationMetric(metric_id="synthetic", value=Decimal("1")),),
        gates=(
            QualificationGateResult(
                gate_id="synthetic",
                passed=True,
                comparator="bool",
                reason_code="synthetic_only",
            ),
        ),
        windows_evaluated=1,
        evaluated_at=candidate.created_at,
        qualification_policy_id="synthetic-source-policy",
        oos_aggregation_hash="c" * 64,
        source="walk_forward_oos",
    )
    original = _make_cached_window()
    window = original.spec.model_copy(
        update={"bundle_hash": "d" * 64, "dataset_registry_hash": "e" * 64}
    )
    simulation = _flat_result(candidate, original.copy_frame(), original)
    config = TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("0.1"),
        taker_fee_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.0001"),
        stop_atr_multiplier=Decimal("1.5"),
        take_profit_atr_multiplier=Decimal("3"),
        trailing_atr_multiplier=Decimal("1"),
    )
    return candidate, qualification, window, simulation, config


def test_cross_scope_window_preserves_original_bindings_and_remains_observation_only(
    tmp_path: Path,
) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    candidate_before = candidate.model_dump_json()
    qualification_before = qualification.model_dump_json()
    path = tmp_path / "confirmation.json"
    evidence = write_confirmation_window_evidence(
        path, candidate, qualification, window, simulation, config
    )
    assert read_confirmation_window_evidence(path, candidate, qualification) == evidence
    assert evidence.candidate_artifact_hash == candidate.artifact_hash
    assert evidence.training_bundle_hash == candidate.bundle_hash
    assert evidence.training_dataset_registry_hash == candidate.dataset_registry_hash
    assert evidence.research_qualification_hash == qualification.qualification_hash
    assert evidence.window == window
    assert evidence.simulation == simulation
    assert evidence.declared_config == config
    assert evidence.evidence_scope == "confirmation_observation_only"
    assert evidence.untouched_isolation_verified is False
    assert evidence.epoch_acceptance_verified is False
    assert evidence.preregistration_verified is False
    assert evidence.execution_authority is False
    assert candidate.model_dump_json() == candidate_before
    assert qualification.model_dump_json() == qualification_before
    assert (
        write_confirmation_window_evidence(
            path, candidate, qualification, window, simulation, config
        )
        == evidence
    )
    assert tuple(tmp_path.iterdir()) == (path,)


def test_legacy_confirmation_without_funding_fields_remains_readable(tmp_path: Path) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    legacy_window = window.model_copy(update={"funding_artifact_hash": None})
    legacy_simulation = simulation.model_copy(
        update={
            "simulation_version": 2,
            "funding_artifact_hash": None,
            "total_funding_payment": Decimal("0"),
        }
    )
    path = tmp_path / "legacy-confirmation.json"
    write_confirmation_window_evidence(path, candidate, qualification, window, simulation, config)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("evidence_hash", None)
    payload["window"] = legacy_window.model_dump(mode="json")
    payload["simulation"] = legacy_simulation.model_dump(mode="json")
    payload["window"].pop("funding_artifact_hash", None)
    payload["simulation"].pop("total_funding_payment", None)
    payload["simulation"].pop("funding_artifact_hash", None)
    for trade in payload["simulation"]["trades"]:
        trade.pop("funding_payment", None)
    payload["declared_config"].pop("funding_mode", None)
    payload["evidence_hash"] = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = read_confirmation_window_evidence(path, candidate, qualification)

    assert loaded.simulation.simulation_version == 2
    assert loaded.window.funding_artifact_hash is None


def test_new_confirmation_writer_rejects_legacy_simulation(tmp_path: Path) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    legacy_window = window.model_copy(update={"funding_artifact_hash": None})
    legacy_simulation = simulation.model_copy(
        update={
            "simulation_version": 2,
            "funding_artifact_hash": None,
            "total_funding_payment": Decimal("0"),
        }
    )
    path = tmp_path / "absent" / "confirmation.json"

    with pytest.raises(DomainViolation, match="funding"):
        write_confirmation_window_evidence(
            path, candidate, qualification, legacy_window, legacy_simulation, config
        )

    assert not path.parent.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "candidate_hash",
        "qualification_hash",
        "rejected",
        "non_oos",
        "qualification_id",
        "qualification_candidate_hash",
        "qualification_bundle",
        "qualification_registry",
        "same_bundle",
        "same_registry",
        "symbol",
        "timeframe",
        "starting_equity",
        "risk_config",
    ],
)
def test_confirmation_rejects_invalid_sources_before_any_filesystem_work(
    tmp_path: Path,
    fault: str,
) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    if fault == "candidate_hash":
        candidate = candidate.model_copy(update={"artifact_hash": "0" * 64})
    elif fault == "qualification_hash":
        qualification = qualification.model_copy(update={"qualification_hash": "0" * 64})
    elif fault in {
        "rejected",
        "non_oos",
        "qualification_id",
        "qualification_candidate_hash",
        "qualification_bundle",
        "qualification_registry",
    }:
        changes = {
            "rejected": {"decision": "rejected"},
            "non_oos": {"source": "creator_evaluator"},
            "qualification_id": {"candidate_id": "cand-synthetic-foreign"},
            "qualification_candidate_hash": {"candidate_artifact_hash": "0" * 64},
            "qualification_bundle": {"bundle_hash": "0" * 64},
            "qualification_registry": {"dataset_registry_hash": "0" * 64},
        }
        qualification = qualification.model_copy(update=changes[fault])
        qualification = qualification.model_copy(
            update={"qualification_hash": _qualification_content_hash(qualification)}
        )
    elif fault in {"same_bundle", "same_registry", "symbol", "timeframe"}:
        changes = {
            "same_bundle": {"bundle_hash": candidate.bundle_hash},
            "same_registry": {"dataset_registry_hash": candidate.dataset_registry_hash},
            "symbol": {"symbol": "ETHUSDT"},
            "timeframe": {"timeframe": "15m"},
        }
        window = window.model_copy(update=changes[fault])
    else:
        config = config.model_copy(
            update={
                "starting_equity" if fault == "starting_equity" else "position_fraction": Decimal(
                    "0.2"
                )
            }
        )
    path = tmp_path / "absent" / "confirmation.json"
    with pytest.raises(DomainViolation, match="confirmation"):
        write_confirmation_window_evidence(
            path, candidate, qualification, window, simulation, config
        )
    assert not path.parent.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "candidate",
        "training",
        "qualification",
        "timeframe",
        "authority",
        "end",
        "accounting",
    ],
)
def test_confirmation_reader_rejects_tampering_even_with_recomputed_outer_hash(
    tmp_path: Path,
    fault: str,
) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    path = tmp_path / "confirmation.json"
    saved = write_confirmation_window_evidence(
        path, candidate, qualification, window, simulation, config
    )
    updates = {
        "hash": {"research_qualification_hash": "0" * 64},
        "candidate": {"candidate_artifact_hash": "0" * 64},
        "training": {"training_bundle_hash": "0" * 64},
        "qualification": {"research_qualification_hash": "0" * 64},
        "timeframe": {"window": window.model_copy(update={"timeframe": "15m"})},
        "authority": {"epoch_acceptance_verified": True},
        "end": {
            "simulation": simulation.model_copy(
                update={
                    "equity_curve": (
                        EquityPoint(timestamp=window.time_end, equity=simulation.final_equity),
                    )
                }
            )
        },
        "accounting": {"simulation": simulation.model_copy(update={"total_fees": Decimal("1")})},
    }
    changed = saved.model_copy(update=updates[fault])
    payload = changed.model_dump(mode="json")
    if fault != "hash":
        payload["evidence_hash"] = _content_hash(changed)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainViolation, match="confirmation"):
        read_confirmation_window_evidence(path, candidate, qualification)


@pytest.mark.parametrize("fault", ["candidate_risk", "qualification_gate", "config", "warmup"])
def test_confirmation_revalidates_bypassed_nested_models(tmp_path: Path, fault: str) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    if fault == "candidate_risk":
        risk = candidate.strategy.risk.model_copy(update={"position_fraction": Decimal("2")})
        candidate = candidate.model_copy(
            update={"strategy": candidate.strategy.model_copy(update={"risk": risk})}
        )
    elif fault == "qualification_gate":
        gate = qualification.gates[0].model_copy(update={"passed": False})
        qualification = qualification.model_copy(update={"gates": (gate,)})
    elif fault == "config":
        config = config.model_copy(update={"position_fraction": Decimal("2")})
    else:
        simulation = simulation.model_copy(
            update={
                "equity_curve": (
                    EquityPoint(
                        timestamp=window.time_start - timedelta(minutes=5),
                        equity=simulation.starting_equity,
                    ),
                )
            }
        )
    path = tmp_path / "absent" / "confirmation.json"
    with pytest.raises(DomainViolation, match="confirmation"):
        write_confirmation_window_evidence(
            path, candidate, qualification, window, simulation, config
        )
    assert not path.parent.exists()


def test_confirmation_does_not_widen_normal_oos_scope_guards(tmp_path: Path) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    path = tmp_path / "confirmation.json"
    write_confirmation_window_evidence(path, candidate, qualification, window, simulation, config)
    with pytest.raises(DomainViolation, match="invalid window"):
        read_window_simulation_evidence(path)
    with pytest.raises(DomainViolation, match="scope mismatch"):
        write_window_simulation_evidence(
            tmp_path / "absent" / "oos.json", candidate, window, simulation
        )
    assert not (tmp_path / "absent").exists()


def test_confirmation_preserves_existing_files_on_conflict_and_cleans_failed_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, qualification, window, simulation, config = _inputs()
    path = tmp_path / "confirmation.json"
    write_confirmation_window_evidence(path, candidate, qualification, window, simulation, config)
    before = path.read_bytes()
    changed_config = config.model_copy(update={"taker_fee_rate": Decimal("0.0006")})
    with pytest.raises(DomainViolation, match="immutable"):
        write_confirmation_window_evidence(
            path, candidate, qualification, window, simulation, changed_config
        )
    assert path.read_bytes() == before

    def fail_link(*args, **kwargs):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="synthetic"):
        write_confirmation_window_evidence(
            tmp_path / "new.json", candidate, qualification, window, simulation, config
        )
    assert tuple(tmp_path.iterdir()) == (path,)
