from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .model_audit import ModelCallAudit, read_model_call_audit
from .model_policy import ResearchModelPolicy, research_model_policy_content_hash


def load_verified_model_call_audit(
    audit_path: Path,
    *,
    policy: ResearchModelPolicy,
) -> ModelCallAudit:
    """Load a persisted audit only after exact policy and pinned-role verification."""
    if research_model_policy_content_hash(policy) != policy.policy_hash:
        raise DomainViolation("research model policy hash mismatch")

    audit = read_model_call_audit(audit_path)
    if audit.policy_id != policy.policy_id or audit.policy_hash != policy.policy_hash:
        raise DomainViolation("model call audit policy binding is invalid")

    role_policy = next((item for item in policy.roles if item.role == audit.role), None)
    if role_policy is None:
        raise DomainViolation("model call audit role binding is invalid")
    if (audit.provider, audit.model_id) != (role_policy.provider, role_policy.model_id):
        raise DomainViolation("model call audit provider-model binding is invalid")
    return audit


__all__ = ["load_verified_model_call_audit"]
