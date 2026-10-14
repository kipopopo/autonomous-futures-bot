from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts/run_scalper_development_grid.py"
    spec = importlib.util.spec_from_file_location("run_scalper_development_grid", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_grid_expands_frozen_axes_and_exclusions() -> None:
    runner = _load_runner()
    protocol = {
        "status": "FROZEN_BEFORE_EVALUATION",
        "selection_interval": {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
        "symbols": ["LINKUSDT"],
        "reference_reports": {"LINKUSDT": {"path": "baseline.json", "sha256": "a" * 64}},
        "distance_thresholds": ["-2.5", "-3.5"],
        "target_atr_multipliers": ["2.0", "2.2"],
        "excluded_combinations": [
            {
                "symbol": "LINKUSDT",
                "distance_threshold": "-2.5",
                "target_atr_multiplier": "2.0",
            }
        ],
    }

    jobs = runner.expand_jobs(protocol)

    assert len(jobs) == 3
    assert all(job["reference_report_sha256"] == "a" * 64 for job in jobs)
    assert not any(
        job["distance_threshold"] == "-2.5" and job["target_atr_multiplier"] == "2.0"
        for job in jobs
    )


def test_development_grid_rejects_unfrozen_or_invalid_parameters() -> None:
    runner = _load_runner()
    protocol = {
        "status": "DRAFT",
        "selection_interval": {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
        "symbols": ["LINKUSDT"],
        "reference_reports": {"LINKUSDT": {"path": "baseline.json", "sha256": "a" * 64}},
        "distance_thresholds": ["-2.5"],
        "target_atr_multipliers": ["0"],
    }

    with pytest.raises(ValueError, match="frozen"):
        runner.expand_jobs(protocol)

    protocol["status"] = "FROZEN_BEFORE_EVALUATION"
    with pytest.raises(ValueError, match="positive"):
        runner.expand_jobs(protocol)


def test_development_grid_checks_frozen_input_hashes(tmp_path: Path) -> None:
    runner = _load_runner()
    runner.REPO = tmp_path
    source = tmp_path / "nested" / "input.json"
    source.parent.mkdir()
    source.write_text("official-data", encoding="utf-8")
    protocol = {
        "inputs": {"commissions": "nested/input.json"},
        "input_fingerprints": [
            {
                "path": "nested\\input.json",
                "sha256": hashlib.sha256(b"official-data").hexdigest(),
            }
        ],
    }

    runner.validate_inputs(protocol)

    source.write_text("changed-data", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        runner.validate_inputs(protocol)


def test_development_grid_requires_commissions_in_frozen_fingerprints(tmp_path: Path) -> None:
    runner = _load_runner()
    runner.REPO = tmp_path
    commission_path = tmp_path / "commission.json"
    commission_path.write_text("authenticated-rates", encoding="utf-8")
    protocol = {
        "inputs": {"commissions": "commission.json"},
        "input_fingerprints": [],
    }

    with pytest.raises(ValueError, match="must be fingerprinted"):
        runner.validate_inputs(protocol)


def test_development_grid_rechecks_frozen_inputs_after_jobs(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    runner.REPO = tmp_path
    commission_path = tmp_path / "commission.json"
    commission_path.write_text("frozen-rates", encoding="utf-8")
    protocol = {
        "status": "FROZEN_BEFORE_EVALUATION",
        "selection_interval": {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
        "symbols": ["LINKUSDT"],
        "reference_reports": {"LINKUSDT": {"path": "reference.json", "sha256": "a" * 64}},
        "distance_thresholds": ["-2.5"],
        "target_atr_multipliers": ["2.0"],
        "inputs": {"commissions": "commission.json"},
        "input_fingerprints": [
            {
                "path": "commission.json",
                "sha256": hashlib.sha256(b"frozen-rates").hexdigest(),
            }
        ],
        "max_workers": 1,
        "output_directory": "output",
        "started_at_utc": "2026-10-14T00:00:00+00:00",
    }
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    def mutate_after_job(_job, _protocol, _output):
        commission_path.write_text("changed-rates", encoding="utf-8")
        return {
            "symbol": "LINKUSDT",
            "distance_threshold": "-2.5",
            "target_atr_multiplier": "2.0",
            "status": "COMPLETED",
        }

    monkeypatch.setattr(runner, "run_job", mutate_after_job)

    with pytest.raises(ValueError, match="hash mismatch"):
        runner.run_grid(protocol_path)

    assert not (tmp_path / "output/grid-summary.json").exists()


def test_development_grid_rejects_protocol_mutation_during_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _load_runner()
    runner.REPO = tmp_path
    commission_path = tmp_path / "commission.json"
    commission_path.write_text("frozen-rates", encoding="utf-8")
    protocol = {
        "status": "FROZEN_BEFORE_EVALUATION",
        "selection_interval": {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
        "symbols": ["LINKUSDT"],
        "reference_reports": {"LINKUSDT": {"path": "reference.json", "sha256": "a" * 64}},
        "distance_thresholds": ["-2.5"],
        "target_atr_multipliers": ["2.0"],
        "inputs": {"commissions": "commission.json"},
        "input_fingerprints": [
            {
                "path": "commission.json",
                "sha256": hashlib.sha256(b"frozen-rates").hexdigest(),
            }
        ],
        "max_workers": 1,
        "output_directory": "output",
        "started_at_utc": "2026-10-14T00:00:00+00:00",
    }
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    def mutate_protocol_after_job(_job, _protocol, _output):
        protocol_path.write_text(json.dumps({**protocol, "mutated": True}), encoding="utf-8")
        return {
            "symbol": "LINKUSDT",
            "distance_threshold": "-2.5",
            "target_atr_multiplier": "2.0",
            "status": "COMPLETED",
        }

    monkeypatch.setattr(runner, "run_job", mutate_protocol_after_job)

    with pytest.raises(ValueError, match="protocol changed"):
        runner.run_grid(protocol_path)

    assert not (tmp_path / "output/grid-summary.json").exists()


def test_development_grid_passes_equity_scenario_to_candidate_runner(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _load_runner()
    runner.REPO = tmp_path
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps({"family": "MACRO_SCALPER", "symbol": "LINKUSDT", "decision": "REJECTED"}),
        encoding="utf-8",
    )
    job = {
        "symbol": "LINKUSDT",
        "distance_threshold": "-2.5",
        "target_atr_multiplier": "2.0",
        "reference_report": str(reference),
        "reference_report_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
    }
    output = tmp_path / "reports"
    report_path = output / "LINKUSDT-report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "report_hash": "a" * 64,
                "candidate_decision_on_development_sample": "REJECTED",
                "metrics": {},
                "gates": {},
            }
        ),
        encoding="utf-8",
    )
    protocol = {
        "inputs": {
            "cache": "cache",
            "filters": "filters.json",
            "funding_directory": "funding",
            "equity_evidence": "capital.json",
            "commissions": "commissions.json",
        },
        "selection_interval": {"start": "2024-01-01"},
    }
    event = {
        "event": "DEVELOPMENT_REPLAY_RECORDED",
        "path": "reports/LINKUSDT-report.json",
        "candidate_decision_on_development_sample": "REJECTED",
        "metrics": {},
        "gates": {},
    }
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)

    runner.run_job(job, protocol, output)

    assert captured["command"][captured["command"].index("--equity-evidence") + 1] == str(
        tmp_path / "capital.json"
    )
    assert captured["command"][captured["command"].index("--commissions") + 1] == str(
        tmp_path / "commissions.json"
    )
