"""Append-only fresh-epoch acceptances; caller-owned checkpoints are the trust anchor.

No function certifies legacy history, authorizes a provider, or grants execution.
Keep the current checkpoint outside this journal. Never derive it from journal rows.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact, _artifact_content_hash
from .creator_proposals import (
    CreatorProposal,
    CreatorProposalOutcome,
    _outcome_content_hash,
    canonical_creator_candidate_id,
    proposal_content_hash,
)


class CreatorEpochCheckpoint(DomainModel):
    epoch_id: str = Field(pattern=r"^epoch-[a-z0-9][a-z0-9-]{0,47}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence: int = Field(ge=0)
    head_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreatorEpochProviderPermit(DomainModel):
    """Separate operator approval; genesis and caller-selected pins never grant calls."""

    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    checkpoint: CreatorEpochCheckpoint
    journal: Path
    control: Path
    checkpoint_file: Path
    ledger_path: Path | None = None
    lifecycle_path: Path | None = None
    qualification_path: Path | None = None
    qualification_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    writer_uid: int = Field(ge=1)
    provider: Literal["google_ai_studio"]
    model: str = Field(min_length=1, max_length=100)
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    critic_calls: Literal[1]
    creator_calls: Literal[1]

    @model_validator(mode="after")
    def feedback_source_is_exclusive(self) -> CreatorEpochProviderPermit:
        has_oos = self.qualification_path is not None
        if (
            (self.ledger_path is not None) == has_oos
            or has_oos != (self.qualification_hash is not None)
            or (has_oos and self.lifecycle_path is not None)
        ):
            raise ValueError("permit requires exactly one ledger or hash-bound OOS source")
        return self

    @field_validator("expires_at")
    @classmethod
    def expiry_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Creator epoch provider permit expiry must be UTC")
        return value.astimezone(UTC)


def _require_protected_epoch_file(path: Path, owner_uid: int) -> None:
    current = path.absolute()
    for entry in (current, *current.parents):
        metadata = entry.lstat()
        if (
            metadata.st_uid not in ({owner_uid} if entry == current else {0, owner_uid})
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not (
                stat.S_ISREG(metadata.st_mode)
                if entry == current
                else stat.S_ISDIR(metadata.st_mode)
            )
        ):
            raise DomainViolation("Creator epoch provider authority is not operator-protected")


def _read_protected_epoch_pin(path: Path) -> str:
    _require_protected_epoch_file(path, 0)
    checked = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), encoding="utf-8") as stream:
        opened = os.fstat(stream.fileno())
        if (
            opened.st_uid != 0
            or opened.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino)
        ):
            raise DomainViolation("Creator epoch provider authority is not operator-protected")
        content = stream.read(65537)
        if len(content) > 65536:
            raise DomainViolation("Creator epoch provider pin exceeds size limit")
        return content


def read_creator_epoch_provider_permit(
    path: Path,
    *,
    journal: Path,
    control: Path,
    checkpoint_file: Path,
    cycle_id: str,
    provider: str,
    model: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    ledger_path: Path | None = None,
    lifecycle_path: Path | None = None,
    qualification_path: Path | None = None,
    qualification_hash: str | None = None,
    now: datetime | None = None,
) -> CreatorEpochProviderPermit:
    """Verify a root-owned bounded grant before credentials, requests or outputs.

    The grant is independent of immutable genesis policy and does not change it.
    Its trusted installation and source/runtime protection require separate approval.
    """
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() != UTC.utcoffset(current_time):
        raise DomainViolation("Creator epoch provider preflight time must be UTC")
    try:
        permit = CreatorEpochProviderPermit.model_validate_json(_read_protected_epoch_pin(path))
        get_uid = getattr(os, "geteuid", None)
        if not callable(get_uid) or get_uid() != permit.writer_uid:
            raise DomainViolation("Creator epoch provider requires the approved operator writer")
        _require_protected_epoch_file(journal, permit.writer_uid)
        _require_protected_epoch_file(control, permit.writer_uid)
        checkpoint = CreatorEpochCheckpoint.model_validate_json(
            _read_protected_epoch_pin(checkpoint_file)
        )
        read_creator_epoch_control(control, journal, checkpoint)
        if (
            checkpoint != permit.checkpoint
            or permit.journal != journal.resolve()
            or permit.control != control.resolve()
            or permit.checkpoint_file != checkpoint_file.resolve()
            or permit.cycle_id != cycle_id
            or permit.provider != provider
            or permit.model != model
            or permit.bundle_hash != bundle_hash
            or permit.dataset_registry_hash != dataset_registry_hash
            or permit.ledger_path != (ledger_path.resolve() if ledger_path else None)
            or permit.lifecycle_path != (lifecycle_path.resolve() if lifecycle_path else None)
            or permit.qualification_path
            != (qualification_path.resolve() if qualification_path else None)
            or permit.qualification_hash != qualification_hash
            or permit.expires_at <= current_time
        ):
            raise DomainViolation("Creator epoch provider permit scope mismatch or expired")
        return permit
    except (OSError, ValueError) as exc:
        raise DomainViolation("Creator epoch provider permit is unavailable or invalid") from exc


def reserve_creator_epoch_provider_permit(
    permit: CreatorEpochProviderPermit, *, permit_path: Path
) -> None:
    """Consume the entire two-call budget once, even if later credential/setup work fails."""
    marker = permit.journal.parent / f".provider-{permit.cycle_id}.reserved"
    try:
        current = read_creator_epoch_provider_permit(
            permit_path,
            journal=permit.journal,
            control=permit.control,
            checkpoint_file=permit.checkpoint_file,
            cycle_id=permit.cycle_id,
            provider=permit.provider,
            model=permit.model,
            bundle_hash=permit.bundle_hash,
            dataset_registry_hash=permit.dataset_registry_hash,
            ledger_path=permit.ledger_path,
            lifecycle_path=permit.lifecycle_path,
            qualification_path=permit.qualification_path,
            qualification_hash=permit.qualification_hash,
        )
        if current != permit:
            raise DomainViolation("Creator epoch provider permit changed after preflight")
        get_uid = getattr(os, "geteuid", None)
        if not callable(get_uid) or get_uid() != permit.writer_uid:
            raise DomainViolation("Creator epoch provider requires the approved operator writer")
        _require_protected_epoch_file(permit.journal, permit.writer_uid)
        _require_protected_epoch_file(permit.control, permit.writer_uid)
        read_creator_epoch_control(permit.control, permit.journal, permit.checkpoint)
        if permit.expires_at <= datetime.now(UTC):
            raise DomainViolation("Creator epoch provider permit expired")
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "cycle_id": permit.cycle_id,
                    "permit_hash": sha256(permit.model_dump_json().encode()).hexdigest(),
                    "status": "reserved_before_credentials",
                },
                stream,
                sort_keys=True,
            )
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(marker.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        raise DomainViolation("Creator epoch provider budget already reserved") from None
    except OSError as exc:
        # Preserve any partial marker; a setup failure is not permission to retry.
        raise DomainViolation("Creator epoch provider budget reservation failed") from exc


def _hash(*values: object) -> str:
    return sha256(json.dumps(values, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _bind(
    checkpoint: CreatorEpochCheckpoint,
    proposal: CreatorProposal,
    candidate: CreatorCandidateArtifact,
    outcome: CreatorProposalOutcome,
) -> None:
    if (
        proposal_content_hash(proposal) != proposal.proposal_hash
        or _artifact_content_hash(candidate) != candidate.artifact_hash
        or _outcome_content_hash(outcome) != outcome.outcome_hash
        or outcome.decision != "accepted"
        or outcome.proposal_id != proposal.proposal_id
        or outcome.proposal_hash != proposal.proposal_hash
        or outcome.research_run_id != proposal.research_run_id
        or outcome.candidate_id != candidate.candidate_id
        or outcome.candidate_artifact_hash != candidate.artifact_hash
        or proposal.strategy != candidate.strategy
        or candidate.candidate_id
        != canonical_creator_candidate_id(candidate.strategy, epoch_id=checkpoint.epoch_id)
    ):
        raise DomainViolation("Creator epoch acceptance binding is invalid")


def create_creator_epoch(path: Path, *, epoch_id: str, policy_hash: str) -> CreatorEpochCheckpoint:
    """Initialize once after owner policy review; return the external genesis checkpoint."""
    checkpoint = CreatorEpochCheckpoint(
        epoch_id=epoch_id,
        policy_hash=policy_hash,
        sequence=0,
        head_hash=_hash("creator-epoch-v1", epoch_id, policy_hash),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DomainViolation("Creator epoch journal already exists") from None
    os.close(descriptor)
    # Failed initialization remains present and unusable, never silently reset.
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            "CREATE TABLE epoch (epoch_id TEXT NOT NULL, policy_hash TEXT NOT NULL);"
            "CREATE TABLE acceptances (sequence INTEGER PRIMARY KEY, "
            "proposal_id TEXT NOT NULL UNIQUE, candidate_id TEXT NOT NULL UNIQUE, "
            "previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL, "
            "proposal TEXT NOT NULL, candidate TEXT NOT NULL, outcome TEXT NOT NULL);"
            "CREATE TRIGGER immutable_acceptances_update BEFORE UPDATE ON acceptances "
            "BEGIN SELECT RAISE(ABORT, 'immutable epoch acceptance'); END;"
            "CREATE TRIGGER immutable_acceptances_delete BEFORE DELETE ON acceptances "
            "BEGIN SELECT RAISE(ABORT, 'immutable epoch acceptance'); END;"
            "CREATE TRIGGER immutable_epoch_update BEFORE UPDATE ON epoch "
            "BEGIN SELECT RAISE(ABORT, 'immutable epoch policy'); END;"
            "CREATE TRIGGER immutable_epoch_delete BEFORE DELETE ON epoch "
            "BEGIN SELECT RAISE(ABORT, 'immutable epoch policy'); END;"
        )
        conn.execute("INSERT INTO epoch VALUES (?, ?)", (epoch_id, policy_hash))
    verify_creator_epoch(path, checkpoint)
    return checkpoint


def _verified_acceptances(
    conn: sqlite3.Connection,
    checkpoint: CreatorEpochCheckpoint,
) -> tuple[tuple[CreatorCandidateArtifact, CreatorProposalOutcome], ...]:
    if conn.execute("SELECT epoch_id, policy_hash FROM epoch").fetchall() != [
        (checkpoint.epoch_id, checkpoint.policy_hash)
    ]:
        raise DomainViolation("Creator epoch policy mismatch")
    previous = _hash("creator-epoch-v1", checkpoint.epoch_id, checkpoint.policy_hash)
    accepted: list[tuple[CreatorCandidateArtifact, CreatorProposalOutcome]] = []
    proposals: set[str] = set()
    candidates: set[str] = set()
    # ponytail: full replay per append, incremental verification only if bounded history grows.
    for index, row in enumerate(
        conn.execute(
            "SELECT sequence, proposal_id, candidate_id, previous_hash, event_hash, "
            "proposal, candidate, outcome FROM acceptances ORDER BY sequence"
        ),
        start=1,
    ):
        sequence, proposal_id, candidate_id, previous_hash, event_hash, p, c, o = row
        proposal = CreatorProposal.model_validate_json(p)
        candidate = CreatorCandidateArtifact.model_validate_json(c)
        outcome = CreatorProposalOutcome.model_validate_json(o)
        _bind(checkpoint, proposal, candidate, outcome)
        expected = _hash(
            previous, index, proposal.proposal_hash, candidate.artifact_hash, outcome.outcome_hash
        )
        if (
            sequence != index
            or previous_hash != previous
            or event_hash != expected
            or proposal_id != proposal.proposal_id
            or candidate_id != candidate.candidate_id
            or proposal_id in proposals
            or candidate_id in candidates
        ):
            raise DomainViolation("Creator epoch journal chain is invalid")
        proposals.add(proposal_id)
        candidates.add(candidate_id)
        accepted.append((candidate, outcome))
        previous = event_hash
    if len(accepted) != checkpoint.sequence or previous != checkpoint.head_hash:
        raise DomainViolation("Creator epoch checkpoint mismatch")
    return tuple(accepted)


def _read(
    path: Path, checkpoint: CreatorEpochCheckpoint
) -> tuple[tuple[CreatorCandidateArtifact, CreatorProposalOutcome], ...]:
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            return _verified_acceptances(conn, checkpoint)
    except DomainViolation:
        raise
    except (sqlite3.Error, ValueError) as exc:
        raise DomainViolation("Creator epoch journal is unavailable or invalid") from exc


def verify_creator_epoch(
    path: Path, checkpoint: CreatorEpochCheckpoint
) -> tuple[CreatorProposalOutcome, ...]:
    return tuple(outcome for _, outcome in _read(path, checkpoint))


def create_creator_epoch_control(
    path: Path, journal: Path, checkpoint: CreatorEpochCheckpoint
) -> None:
    """Initialize a separately protected, operator-pinned control store once.

    Its path/policy must come from trusted configuration, not journal discovery.
    This local store does not withstand privileged replacement of both files.
    """
    if checkpoint.sequence != 0:
        raise DomainViolation("Creator epoch control requires empty authorized genesis")
    verify_creator_epoch(journal, checkpoint)
    if path.resolve() == journal.resolve():
        raise DomainViolation("Creator epoch control must be separate from journal")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DomainViolation("Creator epoch control already exists") from None
    os.close(descriptor)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE epoch_control (journal TEXT NOT NULL, epoch_id TEXT NOT NULL, "
            "policy_hash TEXT NOT NULL, sequence INTEGER NOT NULL, head_hash TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO epoch_control VALUES (?, ?, ?, ?, ?)",
            (
                str(journal.resolve()),
                checkpoint.epoch_id,
                checkpoint.policy_hash,
                checkpoint.sequence,
                checkpoint.head_hash,
            ),
        )
    read_creator_epoch_control(path, journal, checkpoint)


def _control_checkpoint(
    conn: sqlite3.Connection,
    journal: Path,
    expected: CreatorEpochCheckpoint,
    *,
    attached: bool = False,
) -> CreatorEpochCheckpoint:
    table = "trusted.epoch_control" if attached else "epoch_control"
    rows = conn.execute(
        f"SELECT journal, epoch_id, policy_hash, sequence, head_hash FROM {table}"
    ).fetchall()
    if len(rows) != 1 or rows[0][0] != str(journal.resolve()):
        raise DomainViolation("Creator epoch control journal binding mismatch")
    _, epoch_id, policy_hash, sequence, head_hash = rows[0]
    current = CreatorEpochCheckpoint(
        epoch_id=epoch_id,
        policy_hash=policy_hash,
        sequence=sequence,
        head_hash=head_hash,
    )
    if (
        current.epoch_id != expected.epoch_id
        or current.policy_hash != expected.policy_hash
        or current.sequence < expected.sequence
        or (current.sequence == expected.sequence and current.head_hash != expected.head_hash)
    ):
        raise DomainViolation("Creator epoch trusted checkpoint mismatch")
    return current


def read_creator_epoch_control(
    path: Path, journal: Path, expected: CreatorEpochCheckpoint
) -> CreatorEpochCheckpoint:
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            current = _control_checkpoint(conn, journal, expected)
            verify_creator_epoch(journal, current)
            return current
    except DomainViolation:
        raise
    except (sqlite3.Error, ValueError) as exc:
        raise DomainViolation("Creator epoch control is unavailable or invalid") from exc


def read_creator_epoch_configuration(
    journal: Path | None,
    control: Path | None,
    checkpoint_file: Path | None,
) -> CreatorEpochCheckpoint | None:
    """Read explicit operator pins; never initialize or discover authority."""
    if journal is None and control is None and checkpoint_file is None:
        return None
    if journal is None or control is None or checkpoint_file is None:
        raise DomainViolation("Creator epoch requires journal, control and pinned checkpoint")
    try:
        expected = CreatorEpochCheckpoint.model_validate_json(
            checkpoint_file.read_text(encoding="utf-8")
        )
        read_creator_epoch_control(control, journal, expected)
        return expected
    except (OSError, ValueError) as exc:
        raise DomainViolation("Creator epoch configuration is unavailable or invalid") from exc


def append_creator_epoch_acceptance(
    path: Path,
    checkpoint: CreatorEpochCheckpoint,
    proposal: CreatorProposal,
    candidate: CreatorCandidateArtifact,
    outcome: CreatorProposalOutcome,
    *,
    control_path: Path | None = None,
) -> CreatorEpochCheckpoint:
    """Reserve acceptance atomically before external candidate persistence.

    With control_path, SQLite's rollback-journal super-journal commits both stores
    atomically. Without it, this is an evidence-only primitive: runtime rejects
    the uncheckpointed reservation. Never reconstruct a control head from rows.
    """
    _bind(checkpoint, proposal, candidate, outcome)
    updated = checkpoint.model_copy(
        update={
            "sequence": checkpoint.sequence + 1,
            "head_hash": _hash(
                checkpoint.head_hash,
                checkpoint.sequence + 1,
                proposal.proposal_hash,
                candidate.artifact_hash,
                outcome.outcome_hash,
            ),
        }
    )
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as conn, conn:
            if control_path is not None:
                if control_path.resolve() == path.resolve():
                    raise DomainViolation("Creator epoch control must be separate from journal")
                conn.execute(
                    "ATTACH DATABASE ? AS trusted", (control_path.resolve().as_uri() + "?mode=rw",)
                )
                # SQLite multi-file crash atomicity requires disk-backed rollback journals.
                if any(
                    conn.execute(f"PRAGMA {database}.journal_mode").fetchone() != ("delete",)
                    for database in ("main", "trusted")
                ):
                    raise DomainViolation("Creator epoch requires rollback-journal atomicity")
                conn.execute("PRAGMA main.synchronous=FULL")
                conn.execute("PRAGMA trusted.synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            if control_path is not None:
                if _control_checkpoint(conn, path, checkpoint, attached=True) != checkpoint:
                    raise DomainViolation("Creator epoch trusted checkpoint mismatch")
            _verified_acceptances(conn, checkpoint)
            conn.execute(
                "INSERT INTO acceptances VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    updated.sequence,
                    proposal.proposal_id,
                    candidate.candidate_id,
                    checkpoint.head_hash,
                    updated.head_hash,
                    proposal.model_dump_json(),
                    candidate.model_dump_json(),
                    outcome.model_dump_json(),
                ),
            )
            if control_path is not None:
                conn.execute(
                    "UPDATE trusted.epoch_control SET sequence = ?, head_hash = ?",
                    (updated.sequence, updated.head_hash),
                )
    except DomainViolation:
        raise
    except sqlite3.IntegrityError:
        raise DomainViolation("Creator epoch acceptance replay") from None
    except (sqlite3.Error, ValueError) as exc:
        raise DomainViolation("Creator epoch journal is unavailable or invalid") from exc
    verify_creator_epoch(path, updated)
    if control_path is not None:
        read_creator_epoch_control(control_path, path, updated)
    return updated


def require_creator_epoch_candidate(
    path: Path, checkpoint: CreatorEpochCheckpoint, candidate: CreatorCandidateArtifact
) -> None:
    if not any(existing == candidate for existing, _ in _read(path, checkpoint)):
        raise DomainViolation("candidate is quarantined outside the Creator epoch")
