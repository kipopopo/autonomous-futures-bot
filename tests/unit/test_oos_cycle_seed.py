"""Synthetic OOS seeds exercise the real CLI without paper state or network."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

import autonomous_futures.pipeline.autonomous_cycle as cycle
import scripts.run_autonomous_cycle as cli
from autonomous_futures.research.cached_evaluation import CachedEvaluationWindow
from autonomous_futures.research.performance_metrics import calculate_performance_metrics
from autonomous_futures.research.qualification_artifacts import (
    _qualification_content_hash,
    read_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.walk_forward import read_walk_forward_aggregation
from autonomous_futures.research.window_evidence import read_window_simulation_evidence
from tests.unit.test_autonomous_cycle import _make_cached_window
from tests.unit.test_autonomous_research_loop import _write_rejected_seed_artifacts


def test_rejected_oos_seed_runs_research_only_without_creating_a_paper_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_path, qualification_path, candidate, qualification = _write_rejected_seed_artifacts(
        tmp_path
    )
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    baseline = _make_cached_window()
    windows = tuple(
        CachedEvaluationWindow(
            spec=baseline.spec.model_copy(
                update={
                    "window_id": f"window-{index:03d}",
                    "time_start": baseline.spec.time_start + timedelta(days=index),
                    "time_end": baseline.spec.time_end + timedelta(days=index),
                }
            ),
            frame=baseline.copy_frame().assign(
                timestamp=baseline.frame["timestamp"] + timedelta(days=index)
            ),
        )
        for index in range(3)
    )
    monkeypatch.setattr(cli, "load_and_slice_windows", lambda *a, **kw: windows)
    original_simulator = cycle.simulate_candidate_window
    simulation_calls = []

    def observe_simulation(*args, **kwargs):
        simulation_calls.append(kwargs["symbol"])
        return original_simulator(*args, **kwargs)

    monkeypatch.setattr(cycle, "simulate_candidate_window", observe_simulation)
    for name in ("LivePaperEngine", "extract_paper_feedback", "resolve_credential"):
        monkeypatch.setattr(
            cli, name, lambda *a, **kw: pytest.fail("OOS seed is not paper feedback")
        )
    output = tmp_path / "output"
    assert (
        cli.main(
            [
                "--symbol",
                "BTCUSDT",
                "--candidate-path",
                str(candidate_path),
                "--qualification-path",
                str(qualification_path),
                "--output-dir",
                str(output),
                "--bundle-hash",
                candidate.bundle_hash,
                "--dataset-registry-hash",
                candidate.dataset_registry_hash,
                "--cycle-id",
                "cycle-oos-source-test",
                "--now",
                "2026-10-04T00:00:00Z",
            ]
        )
        == 0
    )
    result = json.loads((output / "autonomous-cycle-result.json").read_text())
    audit = json.loads((output / "cycle-audit.json").read_text())
    assert result["prior_feedback_hash"] == qualification.qualification_hash
    assert result["cycle_status"] == "completed_unadmitted"
    assert result["admission_decision"] is None
    assert result["active_candidate_id"] is None
    assert result["stop_reasons"] == ["paper_admission_not_authorized"]
    assert audit["configuration"]["feedback_seed_source"] == "walk_forward_oos"
    assert not list(tmp_path.rglob("*.sqlite3"))
    assert not (tmp_path / "candidate_registry.json").exists()
    assert {name: (tmp_path / name).read_bytes() for name in original} == original
    aggregation = read_walk_forward_aggregation(
        output / "evaluations" / "eval-cycle-oos-source-test.json"
    )
    saved_qualification = read_creator_candidate_qualification_artifact(
        output / "qualifications" / f"{result['qualification_hash']}.json"
    )
    assert saved_qualification.oos_aggregation_hash == aggregation.aggregation_hash
    assert aggregation.aggregation.window_count == len(windows) == len(simulation_calls) == 3
    for window, metrics in zip(windows, aggregation.aggregation.windows, strict=True):
        evidence = read_window_simulation_evidence(
            output
            / "evaluations"
            / "eval-cycle-oos-source-test"
            / window.spec.symbol
            / f"{window.spec.window_id}.json"
        )
        assert evidence.window == window.spec
        assert evidence.candidate_artifact_hash == result["candidate_artifact_hash"]
        assert calculate_performance_metrics(evidence.simulation) == metrics.metrics
    assert len(simulation_calls) == 3  # Readback never reevaluates.


@pytest.mark.parametrize(
    "fault",
    ["candidate_hash", "scope", "not_oos", "empty", "qualified", "tamper", "ledger", "no_permit"],
)
def test_invalid_oos_seed_stops_before_outputs_or_credentials(tmp_path, monkeypatch, fault):
    candidate_path, qualification_path, _, qualification = _write_rejected_seed_artifacts(tmp_path)
    changes = {
        "candidate_hash": {"candidate_artifact_hash": "e" * 64},
        "scope": {"bundle_hash": "e" * 64},
        "not_oos": {"source": "creator_evaluator"},
        "empty": {"windows_evaluated": 0},
        "qualified": {
            "decision": "qualified",
            "gates": tuple(g.model_copy(update={"passed": True}) for g in qualification.gates),
        },
        "tamper": {"qualification_hash": "e" * 64},
    }
    if fault in changes:
        qualification = qualification.model_copy(update=changes[fault])
        if fault != "tamper":
            qualification = qualification.model_copy(
                update={"qualification_hash": _qualification_content_hash(qualification)}
            )
        qualification_path.write_text(qualification.model_dump_json(), encoding="utf-8")
    for name in (
        "load_and_slice_windows",
        "LivePaperEngine",
        "extract_paper_feedback",
        "resolve_credential",
    ):
        monkeypatch.setattr(cli, name, lambda *a, **kw: pytest.fail("invalid OOS input advanced"))
    output = tmp_path / "output"
    argv = [
        "--symbol",
        "BTCUSDT",
        "--candidate-path",
        str(candidate_path),
        "--qualification-path",
        str(qualification_path),
        "--output-dir",
        str(output),
    ]
    if fault == "ledger":
        argv.extend(["--ledger-db", str(tmp_path / "ledger.sqlite3")])
    if fault == "no_permit":
        argv.extend(["--provider", "google_ai_studio"])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert cli.main(argv) == 3
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
