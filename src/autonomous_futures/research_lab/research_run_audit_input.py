from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .model_policy import ResearchModelPolicy, research_model_policy_content_hash
from .research_run_audit import ResearchRunAuditEnvelope
from .research_run_audit_persistence import read_research_run_audit_envelope


def load_verified_research_run_audit_envelope(
    path: Path,
    *,
    policy: ResearchModelPolicy,
) -> ResearchRunAuditEnvelope:
    """Load a persisted run envelope only after exact policy and role verification."""
    if research_model_policy_content_hash(policy) != policy.policy_hash:
        raise DomainViolation("research model policy hash mismatch")

    envelope = read_research_run_audit_envelope(path)
    if envelope.policy_id != policy.policy_id or envelope.policy_hash != policy.policy_hash:
        raise DomainViolation("research run audit envelope policy binding is invalid")

    for audit in envelope.audits:
        role_policy = next((item for item in policy.roles if item.role == audit.role), None)
        if role_policy is None:
            raise DomainViolation("research run audit envelope role binding is invalid")
        if (audit.provider, audit.model_id) != (role_policy.provider, role_policy.model_id):
            raise DomainViolation("research run audit envelope provider-model binding is invalid")
    return envelope


__all__ = ["load_verified_research_run_audit_envelope"]
