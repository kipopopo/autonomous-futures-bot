# Phase 6T Verification — Kainode remote transport preflight

## Decision

Phase 6T is **UNAVAILABLE**. This phase performed only a bounded, read-only
transport preflight for the Kainode research worker required by the pending
Phase 6S cached-only qualification.

No server configuration, package, service, credential, firewall, exchange
client, or research artifact was changed.

## Probes

Target: `147.79.18.15`

```text
ICMP probe:       timeout, 100% packet loss
TCP port 22:     unreachable or closed
Pinned SSH probe: timeout, wrapper exit 124 after 20 seconds
Host key:        no new key accepted; pinned fingerprint remained configured
```

The pinned SSH command did not reach a remote shell, so this is transport
unavailability rather than an authentication, repository, Python, feature, or
qualification result.

## Phase 6S impact

```text
ADX feature implementation: locally verified
Phase 6S remote sync:        unavailable
Phase 6S qualification:     not run
Phase 6S metrics:            unavailable
Temporary runner:            absent
```

No local substitute was used because the immutable Phase 6N parquet scope is
owned by the remote worker. No pass, rejection, or candidate metric is inferred
from the transport failure.

## Local verification

The repository state before this report was clean at the ADX feature commit.
The canonical locked suite remains the valid project command:

```text
uv run --locked pytest -q: 488 passed
```

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

Next action is provider-console/network recovery and a fresh pinned SSH
preflight. Do not retry the Phase 6S cohort until transport and exact-commit
synchronization are verified.
