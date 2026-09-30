"""Fail-closed gate for real Creator requests while historical lineage is ambiguous."""

from __future__ import annotations

from ..domain.errors import DomainViolation


def require_complete_creator_history() -> None:
    """Refuse provider calls until an authoritative, complete history preflight exists.

    Verified registry/artifact collisions and unpersisted accepted proposals
    cannot be adjudicated by a caller-selected subset or an empty snapshot.
    This gate must not be replaced by a directory-presence check.
    """
    raise DomainViolation("complete Creator history and accepted-proposal preflight is unavailable")
