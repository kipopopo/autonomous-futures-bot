# ADR-0002: Isolate research, paper, shadow, demo, and live environments

- **Status:** Accepted
- **Date:** 2026-08-06
- **Decision owners:** Project operator and deterministic runtime authority

## Context

The project has five operational environments with different evidence and execution
risk: `research`, `paper`, `shadow`, `demo`, and `live`. Reusing a storage root, database
namespace, event stream, or credential namespace could make an artifact or order
state appear to belong to the wrong environment. A boolean runtime flag is not a
sufficient safety boundary.

## Decision

Every environment receives a distinct, explicit:

- storage root;
- database namespace;
- event-stream namespace;
- credential namespace.

The domain contract validates uniqueness across all configured environments.
`research`, `paper`, and `shadow` are forbidden from enabling authenticated exchange access.
`demo` and `live` remain separate environments even when an adapter is eventually
implemented. Promotion copies immutable manifests by hash; it does not merge
runtime state or credentials.

The first deterministic defaults are generated under `artifacts/<environment>`
with namespaced database, event, and credential identifiers. Deployment-specific
paths and secret-store handles are supplied later, but must pass the same
uniqueness validation.

## Consequences

### Positive

- Research artifacts cannot silently become paper or live state.
- Paper runtime cannot reach authenticated exchange endpoints through this contract.
- Reconciliation and audit queries have an unambiguous environment identity.
- Environment transitions require an explicit manifest/policy operation.

### Trade-offs

- Each environment needs separate storage and operational housekeeping.
- A later deployment must provision four namespaces even when only research/paper
  are active.
- The contract does not itself provision credentials or authorize live trading;
  those remain later governance and deployment gates.

## Verification

The contract is covered by `tests/unit/test_environment_boundary.py`:

- all five default environments are present and isolated;
- duplicate storage/database namespaces are rejected;
- research/paper/shadow authenticated access is rejected;
- duplicate environment identity is rejected.
