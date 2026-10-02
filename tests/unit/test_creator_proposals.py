from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.contracts import StrategySpec
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_proposals import (
    CreatorProposal,
    build_candidate_from_proposal,
    canonical_creator_candidate_id,
    parse_creator_proposal,
    read_creator_proposal_outcome,
    write_creator_proposal_outcome,
)

BUNDLE_HASH = "a" * 64
REGISTRY_HASH = "b" * 64
CREATED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "proposal_id": "proposal-001",
        "research_run_id": "run-creator-001",
        "hypothesis": "Mean reversion after prior-bar RSI extremes",
        "expected_regime": "range",
        "novelty_reason": "Fresh pair-specific hypothesis",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": "cand-doge-proposal-001",
            "family": "range_mean_reversion",
            "universe": {
                "symbols": ["DOGEUSDT"],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
            "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
            "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
            "vetoes": ["funding_adverse"],
        },
    }


def test_valid_proposal_builds_testing_candidate_without_raw_output() -> None:
    proposal = parse_creator_proposal(_payload())

    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )

    assert isinstance(proposal, CreatorProposal)
    assert candidate.candidate_id == proposal.strategy.strategy_id
    assert candidate.candidate_id != "cand-doge-proposal-001"
    assert candidate.state == "testing"
    assert candidate.bundle_hash == BUNDLE_HASH


def test_historical_strategy_maps_to_the_same_local_candidate_id() -> None:
    payload = _payload()
    proposal = parse_creator_proposal(payload)
    historical_strategy = StrategySpec.model_validate(payload["strategy"])

    assert canonical_creator_candidate_id(historical_strategy) == proposal.strategy.strategy_id


def test_epoch_identity_preserves_legacy_and_isolates_new_candidates() -> None:
    legacy = parse_creator_proposal(_payload())
    first = parse_creator_proposal(_payload(), epoch_id="epoch-20261002")
    second = parse_creator_proposal(_payload(), epoch_id="epoch-other")
    assert len({p.strategy.strategy_id for p in (legacy, first, second)}) == 3
    assert first.strategy.strategy_id == canonical_creator_candidate_id(
        first.strategy, epoch_id="epoch-20261002"
    )
    assert len(first.strategy.strategy_id) == len(legacy.strategy.strategy_id)
    with pytest.raises(ValueError, match="epoch"):
        parse_creator_proposal(_payload(), epoch_id="../legacy")


def test_invalid_or_unsafe_proposal_is_rejected_before_candidate_build() -> None:
    payload = _payload()
    payload["strategy"] = {
        **payload["strategy"],
        "entry": {"long": "__import__('os')", "short": "rsi >= 70"},
    }

    with pytest.raises(ValueError, match="unsafe expression"):
        parse_creator_proposal(payload)


def test_proposal_outcome_is_write_once_and_read_verified(tmp_path: Path) -> None:
    proposal = parse_creator_proposal(_payload())
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=CREATED_AT,
    )
    path = tmp_path / "proposal-outcome.json"

    assert write_creator_proposal_outcome(path, outcome) == outcome
    assert read_creator_proposal_outcome(path) == outcome

    changed = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("changed",),
        recorded_at=CREATED_AT,
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_creator_proposal_outcome(path, changed)


def test_concurrent_outcome_writers_do_not_publish_each_others_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    proposal = parse_creator_proposal(_payload())
    outcomes = tuple(
        proposal.build_outcome(
            decision="accepted",
            candidate_artifact_hash="d" * 64,
            reason_codes=(reason,),
            recorded_at=CREATED_AT,
        )
        for reason in ("first", "second")
    )
    path = tmp_path / "outcome.json"
    barrier = Barrier(2)
    link = os.link

    def synchronized_link(source, target):
        barrier.wait(timeout=5)
        return link(source, target)

    monkeypatch.setattr(os, "link", synchronized_link)

    def write(outcome):
        try:
            return write_creator_proposal_outcome(path, outcome)
        except DomainViolation:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, outcomes))
    assert sum(result is not None for result in results) == 1
    assert all(
        result is None or result == expected
        for result, expected in zip(results, outcomes, strict=True)
    )
    assert read_creator_proposal_outcome(path) in outcomes
    assert tuple(tmp_path.glob(".*.tmp")) == ()


@pytest.mark.parametrize("mode", ["evidence_only", "atomic", "control_failure", "wal"])
def test_epoch_control_requires_durable_acceptance_checkpoint(tmp_path: Path, mode: str) -> None:
    from autonomous_futures.research.creator_epoch import (
        append_creator_epoch_acceptance,
        create_creator_epoch,
        create_creator_epoch_control,
        read_creator_epoch_control,
        verify_creator_epoch,
    )

    journal = tmp_path / "journal.sqlite3"
    control = tmp_path / "control" / "head.sqlite3"
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-test", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    assert read_creator_epoch_control(control, journal, checkpoint) == checkpoint
    proposal = parse_creator_proposal(_payload(), epoch_id=checkpoint.epoch_id)
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=CREATED_AT,
    )
    if mode in ("control_failure", "wal"):
        import sqlite3

        with sqlite3.connect(control) as conn:
            if mode == "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            else:
                conn.execute(
                    "CREATE TRIGGER reject_checkpoint BEFORE UPDATE ON epoch_control "
                    "BEGIN SELECT RAISE(ABORT, 'checkpoint rejected'); END;"
                )
        with pytest.raises(DomainViolation):
            append_creator_epoch_acceptance(
                journal,
                checkpoint,
                proposal,
                candidate,
                outcome,
                control_path=control,
            )
        assert verify_creator_epoch(journal, checkpoint) == ()
        assert read_creator_epoch_control(control, journal, checkpoint) == checkpoint
        return
    updated = append_creator_epoch_acceptance(
        journal,
        checkpoint,
        proposal,
        candidate,
        outcome,
        control_path=control if mode == "atomic" else None,
    )
    with pytest.raises(DomainViolation, match="genesis"):
        create_creator_epoch_control(tmp_path / "replacement-control.sqlite3", journal, updated)
    if mode == "atomic":
        assert read_creator_epoch_control(control, journal, checkpoint) == updated
        control.unlink()
    with pytest.raises(DomainViolation):
        read_creator_epoch_control(control, journal, updated)


@pytest.mark.parametrize("fault", ["missing", "delete", "tamper", "gap", "policy", "subset"])
def test_epoch_acceptance_journal_binds_outcome_and_rejects_replay(
    tmp_path: Path, fault: str
) -> None:
    from autonomous_futures.research.creator_epoch import (
        append_creator_epoch_acceptance,
        create_creator_epoch,
        require_creator_epoch_candidate,
        verify_creator_epoch,
    )

    path = tmp_path / "epoch.sqlite3"
    checkpoint = create_creator_epoch(path, epoch_id="epoch-20261002", policy_hash="c" * 64)
    assert verify_creator_epoch(path, checkpoint) == ()
    proposal = parse_creator_proposal(_payload(), epoch_id=checkpoint.epoch_id)
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=CREATED_AT,
    )
    updated = append_creator_epoch_acceptance(path, checkpoint, proposal, candidate, outcome)
    assert updated.sequence == 1
    assert verify_creator_epoch(path, updated) == (outcome,)
    require_creator_epoch_candidate(path, updated, candidate)
    with pytest.raises(DomainViolation, match="checkpoint"):
        verify_creator_epoch(path, checkpoint)
    with pytest.raises(DomainViolation, match="replay"):
        append_creator_epoch_acceptance(path, updated, proposal, candidate, outcome)
    assert verify_creator_epoch(path, updated) == (outcome,)
    legacy = parse_creator_proposal(_payload())
    old_candidate = build_candidate_from_proposal(
        legacy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )
    with pytest.raises(DomainViolation, match="epoch"):
        require_creator_epoch_candidate(path, updated, old_candidate)
    with pytest.raises(DomainViolation, match="exists"):
        create_creator_epoch(path, epoch_id=checkpoint.epoch_id, policy_hash=checkpoint.policy_hash)
    if fault == "missing":
        path.unlink()
    elif fault == "policy":
        updated = updated.model_copy(update={"policy_hash": "d" * 64})
    elif fault == "subset":
        path = tmp_path / "subset.sqlite3"
        create_creator_epoch(path, epoch_id=checkpoint.epoch_id, policy_hash=checkpoint.policy_hash)
    else:
        import sqlite3

        with sqlite3.connect(path) as conn:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute("DELETE FROM acceptances")
            conn.execute("DROP TRIGGER immutable_acceptances_delete")
            conn.execute("DROP TRIGGER immutable_acceptances_update")
            if fault == "delete":
                conn.execute("DELETE FROM acceptances")
            elif fault == "tamper":
                conn.execute("UPDATE acceptances SET event_hash = ?", ("f" * 64,))
            else:
                conn.execute("UPDATE acceptances SET sequence = 3")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(DomainViolation):
        verify_creator_epoch(path, updated)
    with pytest.raises(DomainViolation):
        require_creator_epoch_candidate(path, updated, candidate)
    assert (path.read_bytes() if path.exists() else None) == before
