# Live-Capable Design Review — USDⓈ-M Futures Only

**Status:** design-only; implementation blocked.

## 1. Scope

Define the future production/live boundary after the completed paper and bounded testnet evidence chain.

```text
paper runtime: complete
bounded testnet lifecycle evidence: complete/frozen
live implementation: not authorized
live credentials: not authorized
live endpoint: disabled
```

This document does not approve live trading. It defines what must be reviewed before any code or credential can cross the boundary.

## 2. Hard separation

```text
paper modules                 local-only
historical research           cached-only
frozen testnet evidence       read-only audit
future live adapter           separate process/package
live credentials               separate secret store
live endpoint                  explicit allow-list only
```

The paper runtime must never import, discover, or call a live adapter. Testnet credentials must never be accepted by a live adapter, and mainnet credentials must never be accepted by testnet code.

## 3. Required live activation artifact

A new immutable `LiveActivationApproval` is required. Existing paper reviews, testnet reviews, testnet designations, and testnet approvals are insufficient.

Required fields:

```text
approval_id
candidate_id + candidate_artifact_hash
paper cohort report hash
paper human-review checkpoint hash
testnet completion summary hash
testnet evidence freeze/review hash
explicit environment = production
explicit venue/product = Binance USDⓈ-M perpetual futures
explicit symbol universe
explicit maximum live quote notional
explicit maximum account capital at risk
explicit maximum concurrent positions
explicit maximum daily loss
explicit order-count/rate cap
explicit kill-switch owner and procedure
reviewer ID
reviewed_at UTC
expires_at UTC
reasoned review notes
```

The artifact must be write-once, hash-bound, conflict-safe, and rejected after expiry or any provenance drift. It must not be convertible from a testnet approval by changing only the environment field.

## 4. Mandatory gates before a live request

Every gate must pass before an order request. One failure means `BLOCKED` and zero network order requests:

1. Environment is exactly production and the endpoint is the explicitly approved production host.
2. Live approval exists, is unexpired, and matches every paper/testnet evidence hash.
3. Account, position, open-order, balance, and position-mode state are reconciled immediately before action.
4. Symbol is in the approved live universe; exchange filters and leverage brackets are fresh and hash-recorded.
5. Quote notional, margin, leverage, and capital-at-risk limits pass independently.
6. Maximum position count and one-position-per-symbol rule pass.
7. Daily loss, cumulative drawdown, and kill-switch state pass.
8. Entry has an explicit reduce-only exit plan and bounded maximum holding policy.
9. No prior order has unknown status; ambiguous state halts the process.
10. Clock skew and `recvWindow` timing checks pass.
11. Secret-store identity and environment identity match the approved account/venue.
12. Audit journal is writable and the pre-request intent is durably recorded before transmission.
13. The process is single-cycle bounded; no unattended retry loop is active.

## 5. Request and response safety

```text
preflight → persist intent → sign → send one request → classify response
```

Unknown execution status must never be retried blindly:

```text
mark UNKNOWN
query by deterministic clientOrderId/orderId
reconcile order + account/user-data state
halt if unresolved
```

The order client must distinguish:

```text
request rejected
request definitely failed
request accepted/filled
request execution status unknown
```

A transport timeout is not proof that no order exists.

## 6. Kill switch and rollback

The kill switch must be executable independently of the strategy process and must:

```text
block new entries
cancel permitted non-reduce-only open orders
permit only explicitly approved reduce-only exits
record operator, timestamp, reason, and resulting state
```

Rollback sequence:

1. Disable live activation at the secret/config boundary.
2. Trigger kill switch.
3. Reconcile account and open orders.
4. Close only according to an explicit reduce-only decision.
5. Preserve all audit rows; never delete or rewrite history.
6. Restore previous code only after account state is reconciled.
7. Verify live endpoint is unreachable from the disabled process.

## 7. Deployment boundary

Live deployment requires a dedicated host/process identity, separate environment file/secret store, separate SQLite/audit paths, separate systemd unit, and explicit firewall/egress policy.

Before deployment:

```text
backup code and databases
verify release SHA
verify systemd unit
verify secret-store mapping without printing values
verify production endpoint allow-list
verify live_enabled=false in default config
run offline full suite
run bounded staging/preflight
```

The first production deployment must not include a scheduler or unattended order loop. A single manually initiated bounded cycle is the only acceptable first activation shape.

## 8. Explicit unresolved blockers

No implementation should begin until these are separately confirmed:

```text
venue/account/product availability and ToS/KYC constraints
jurisdiction and legal/compliance review
live capital amount and maximum capital-at-risk
approved live symbol universe
fee/slippage assumptions for production
kill-switch operator and escalation path
secret-manager choice and rotation procedure
VPS hardening and deployment target
```

No geo, account, KYC, product, or venue restriction may be bypassed.

## 9. Rollout stages after approval

```text
L0 offline live contracts and fake signing vectors
L1 production-config validation with no network
L2 read-only production account reconciliation, separately approved
L3 one manually initiated live order only after fresh approval
L4 immediate reduce-only close and full reconciliation
L5 observation and post-incident review
```

There is no automatic transition from testnet to live.

## 10. Current decision

The current project state remains:

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
new_actions_allowed=false
```

Any live-capable implementation, credential activation, or production request is deferred pending a separate human review of this design and every unresolved blocker above.
