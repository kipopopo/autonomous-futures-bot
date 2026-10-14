from pathlib import Path

import pytest

from autonomous_futures.feed.runtime_hawkes_calibration import (
    load_runtime_hawkes_calibration,
)

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = (
    REPO / "artifacts/qualification/runtime-microstructure/runtime-hawkes-calibration-20261013.json"
)


def test_runtime_calibration_loads_selection_and_independent_validation_evidence():
    calibration = load_runtime_hawkes_calibration(ARTIFACT, REPO)
    assert calibration.beta_per_second > 0
    assert len(calibration.artifact_sha256) == 64
    assert len(calibration.trace_sha256s) >= 2
    assert len(set(calibration.trace_sha256s)) == len(calibration.trace_sha256s)
    assert len(calibration.symbols) == 12


def test_runtime_calibration_rejects_evidence_outside_repository(tmp_path):
    with pytest.raises(ValueError, match="inside the repository"):
        load_runtime_hawkes_calibration(tmp_path / "calibration.json", REPO)
