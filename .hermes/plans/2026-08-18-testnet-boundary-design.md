# Testnet Boundary Design — USDⓈ-M Futures Only

**Status:** design-only; no implementation or credentials authorized.

## 1. Purpose

Define the smallest safe bridge from the completed local paper system to a future Binance USDⓈ-M Futures testnet runtime. This document does not authorize testnet orders, credential use, exchange access, or deployment.

## 2. Current paper boundary remains unchanged

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

The existing paper modules remain local-only and must not import an exchange client, HTTP/WebSocket client, scheduler, credentials loader, or market-data loader.

Future testnet code must be a separate adapter/process boundary. It must not be added to `paper/runtime.py` or make the paper runtime polymorphic through a shared live-looking interface.

## 3. Official Binance facts used by this design

Official USDⓈ-M Futures General Info currently states:

```text
production REST: https://fapi.binance.com
production WebSocket: documented separately
USDⓈ-M testnet REST: https://demo-fapi.binance.com
USDⓈ-M testnet WebSocket: wss://demo-fstream.binance.com
```

The same official page states that timestamps are milliseconds, data is returned oldest-first/newest-last, and some endpoints require API keys. Its HTTP guidance distinguishes failures from `503` unknown execution status; an unknown-status request must be reconciled via order query/user-data evidence before any retry.

Official Quick Start states Futures Testnet is API-only and points to the Futures Demo Trading page for API-key setup. Credentials are therefore a future explicit prerequisite, not a paper/runtime dependency.

Sources:

- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info
- https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/quick-start
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

These URLs and endpoint behavior must be re-verified immediately before implementation because exchange documentation can change.

## 4. Required activation artifact

No testnet action may be attempted without a separate human-approved `TestnetActivationReview` containing:

```text
review_id
candidate_id + candidate_artifact_hash
exact paper cohort report hash
exact paper review checkpoint hash
decision = accept_testnet_designated_candidate
reviewer_id
reviewed_at UTC
expiry UTC
explicit environment = testnet
explicit symbol universe
explicit max quote notional
explicit max concurrent positions
explicit max daily loss
explicit kill-switch owner
```

A paper review checkpoint with `accept_paper_observation` is not sufficient. It only authorizes continued paper observation.

The activation artifact must be immutable/write-once, hash-bound, conflict-safe, and rejected after expiry or binding drift. It must never be accepted for production/live.

## 5. Hard gates before any testnet order

All gates must pass; one failure means `BLOCKED` and zero order requests:

1. Exact environment is `testnet`; no fallback URL.
2. `live_enabled=false` and no production endpoint configured.
3. Activation artifact exists, is valid, unexpired, and matches the reviewed candidate/hash.
4. Candidate is still bound to the reviewed symbol universe and research evidence.
5. Paper cohort is `ready_for_human_review`; no `blocked`, `attention`, `maturing`, stale-mark, or incomplete-accounting report.
6. Current exchange account/position/order state has been reconciled before action.
7. Current local testnet ledger and exchange state have no unresolved drift.
8. Symbol filters, precision, minimum notional, leverage bracket, position mode, and margin mode are explicitly fetched and validated for the exact symbol.
9. Proposed exposure is quote notional, not asset quantity; leverage is applied exactly once.
10. Position limit is one open position per symbol for this project.
11. Daily loss, total exposure, per-symbol notional, and order-count limits pass.
12. Every opening action has an explicit reduce-only exit plan and bounded notional.
13. No ambiguous prior request, unknown order status, or unresolved user-data gap exists.
14. Kill switch is available and tested before the first order.

## 6. Future component boundary

```text
paper evidence + activation artifact
              │
              ▼
      testnet SafetyGate
              │ BLOCKED / APPROVED
              ▼
  testnet reconciliation service
              │
              ▼
     USDⓈ-M TestnetAdapter
       REST signed requests
              │
              ▼
   isolated testnet ledger/audit
```

The future adapter must own:

- explicit testnet base URL allow-list;
- signed request construction and timestamp/`recvWindow` handling;
- exchange error classification;
- deterministic client-order IDs;
- order query and reconciliation;
- testnet-only audit persistence.

The adapter must not be callable from paper modules, and paper events must never be silently copied into testnet orders.

## 7. Unknown execution status rule

For an order request returning an official unknown-status `503` variant:

```text
do not blindly retry
mark local action UNKNOWN
query order by deterministic clientOrderId/orderId
reconcile user-data and REST state
halt if state remains ambiguous
```

A retry is permitted only after reconciliation proves the original request did not create an order and the idempotency contract allows a retry.

## 8. Staged implementation plan after separate approval

### Stage A — offline contracts only

- typed activation artifact;
- endpoint allow-list;
- request signing test vectors with fake secrets only;
- symbol-filter and notional validation;
- error classification;
- idempotency and reconciliation state machine;
- zero-network unit tests.

### Stage B — testnet adapter read-only

- injected HTTP transport;
- public exchange-info/market metadata;
- authenticated account read only after credential approval;
- real testnet connectivity smoke test;
- no order endpoint.

### Stage C — testnet order simulation endpoint

- use the documented test-order capability if still available;
- prove signing, filters, precision, and error handling;
- no actual testnet position mutation.

### Stage D — one bounded testnet lifecycle

Only after a fresh human approval:

```text
one symbol
one bounded notional
one opening order
one reduce-only close
full reconciliation
full audit evidence
```

No multi-symbol rollout, automation, or unattended retries in the first lifecycle.

### Stage E — bounded observation

Observe the testnet lifecycle read-only, reconcile restart behavior, and report failures. A successful testnet order does not authorize live trading.

## 9. Explicitly deferred

```text
credentials
secret manager integration
exchange HTTP client
WebSocket client
testnet order router
testnet scheduler
automatic signal consumer
live endpoint
live credentials
production deployment
```

Each requires a separate review and approval. No testnet implementation is included in this phase.

## 10. Acceptance criteria for this design phase

- Boundary is documented and separate from paper modules.
- Current official testnet URLs and API prerequisites are cited.
- No source code or dependency changes are required.
- No credentials are created, requested, stored, or used.
- Paper authority fields remain false.
- Implementation cannot begin implicitly from a paper review checkpoint.
