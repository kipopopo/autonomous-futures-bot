"""Fresh publication must reject every legacy entry before replacing a manifest."""

from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.admission import StrategyAdmissionDecider
from autonomous_futures.paper.candidate_registry import (
    publish_candidate_admission,
    read_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import write_creator_candidate_artifact
from autonomous_futures.research.creator_epoch import (
    append_creator_epoch_acceptance,
    create_creator_epoch,
    create_creator_epoch_control,
)
from autonomous_futures.research.creator_proposals import (
    build_candidate_from_proposal,
    parse_creator_proposal,
)
from tests.paper_fixtures import write_qualified_paper_fixture
from tests.unit.test_creator_proposals import BUNDLE_HASH, CREATED_AT, REGISTRY_HASH, _payload
from tests.unit.test_paper_candidate_admission import _build_test_candidate


@pytest.mark.parametrize("mode", ["valid", "new_legacy", "retained_legacy"])
def test_epoch_publication_validates_complete_result_before_write(
    tmp_path: Path, mode: str
) -> None:
    journal = tmp_path / "epoch.sqlite3"
    control = tmp_path / "control.sqlite3"
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-publication", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    proposal = parse_creator_proposal(_payload(), epoch_id=checkpoint.epoch_id)
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-publication",
        research_seed=1,
        created_at=CREATED_AT,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=CREATED_AT,
    )
    checkpoint = append_creator_epoch_acceptance(
        journal,
        checkpoint,
        proposal,
        candidate,
        outcome,
        control_path=control,
    )
    decider = StrategyAdmissionDecider(
        epoch_path=journal,
        epoch_checkpoint=checkpoint,
        epoch_control=control,
    )
    manifest = tmp_path / "registry.json"
    legacy = _build_test_candidate()
    legacy_path = tmp_path / "legacy.json"
    write_creator_candidate_artifact(legacy_path, legacy)
    legacy_qualification = write_qualified_paper_fixture(legacy_path, legacy)
    if mode == "retained_legacy":
        publish_candidate_admission(
            manifest,
            "BTCUSDT",
            legacy.candidate_id,
            legacy.artifact_hash,
            legacy_path,
            legacy_qualification,
            admitted_at=CREATED_AT,
        )
    if mode == "new_legacy":
        selected, artifact_path, qualification, symbol = (
            legacy,
            legacy_path,
            legacy_qualification,
            "BTCUSDT",
        )
    else:
        artifact_path = tmp_path / "fresh.json"
        write_creator_candidate_artifact(artifact_path, candidate)
        qualification = write_qualified_paper_fixture(artifact_path, candidate)
        selected, symbol = candidate, "DOGEUSDT"
    before = manifest.read_bytes() if manifest.exists() else None

    def publish():
        return publish_candidate_admission(
            manifest,
            symbol,
            selected.candidate_id,
            selected.artifact_hash,
            artifact_path,
            qualification,
            admitted_at=CREATED_AT,
            admission_decider=decider,
        )

    if mode == "valid":
        result = publish()
        assert read_candidate_registry(manifest) == result
        assert result.symbols[symbol].candidate_artifact_hash == candidate.artifact_hash
    else:
        with pytest.raises(DomainViolation, match="epoch"):
            publish()
        assert (manifest.read_bytes() if manifest.exists() else None) == before
