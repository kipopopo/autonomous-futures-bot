# Phase 3AE Verification — Read-Only Metric-Quality Qualification Evidence API/UI

## Status

**GREEN — Phase 3AE scope verified locally.**

Phase 3AE exposes already-verified, persisted Phase 3AC metric-quality qualification evidence through a narrow read-only API and the existing Learner dashboard.

```text
persisted qualification evidence
→ typed persisted policy parsing
→ Phase 3AD full-chain verified loader
→ GET /api/v1/learner/metric-quality-qualification
→ typed frontend payload + read-only learner model
→ observational evidence card
```

It does **not** create evidence, evaluate a policy, mutate an artifact, train a learner, promote a candidate, activate paper trading, connect to an exchange, or route an order.

## Model-tier decision

Runtime used:

```text
model: gpt-5.6-terra
provider: openai-codex
```

This was a bounded read-only API/UI integration built on established immutable evidence contracts and the Phase 3AD verifier. `terra` remained appropriate. No silent model switch occurred.

## Delivered surface

### API

New read-only endpoint:

```text
GET /api/v1/learner/metric-quality-qualification
```

The endpoint is configured solely with explicit persisted paths:

```text
AFBOT_LEARNER_METRIC_EVALUATION_PATH
AFBOT_LEARNER_METRIC_QUALITY_REVIEW_EVIDENCE_PATH
AFBOT_LEARNER_METRIC_QUALITY_DECISION_PATH
AFBOT_LEARNER_METRIC_QUALITY_POLICY_PATH
AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_EVIDENCE_PATH
AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_POLICY_PATH
```

New adapter:

```text
src/autonomous_futures/api/metric_quality_qualification.py
```

The adapter parses both policy files into their existing typed models and delegates all evidence verification to:

```text
load_verified_learner_metric_quality_qualification_evidence(...)
```

No canonical JSON, hash, evidence-reconstruction, or qualification logic was duplicated in the API layer.

### HTTP contract

| Condition | HTTP response | Meaning |
|---|---:|---|
| Complete verified chain | `200` | Typed persisted evidence returned |
| Required evidence/policy path missing | `404` | `learner metric-quality qualification evidence unavailable` |
| Malformed policy, hash drift, semantic drift, or any other integrity failure | `503` | `learner metric-quality qualification evidence integrity verification failed` |
| `POST` or any other non-GET method | `405` | Route remains read-only |

The response contains the original typed evidence plus `verified=true`; it does not infer a result from missing input.

### UI

The Learner page has one dedicated full-width card:

```text
Metric-quality qualification evidence
├── source metric-quality decision: PASSED | FAILED
├── qualification result: QUALIFIED | REJECTED
├── source / qualification policy identities and SHA-256 bindings
├── persisted gate outcomes and evaluated window count
├── MYT/GMT+8 evaluated timestamp and evidence hash
└── unpromoted · paper activation off · execution authority off
```

The UI deliberately keeps the source decision and qualification decision separate:

```text
source PASSED / FAILED != qualification QUALIFIED / REJECTED
```

A source `PASSED` and a qualification `QUALIFIED` are displayed as evidence only. Neither is represented as promotion, profitability, paper activation, exchange access, or execution permission.

`404` maps to `UNAVAILABLE`; a non-`404` endpoint failure maps to `INTEGRITY UNAVAILABLE`. Neither state is rendered as a failed/rejected decision.

## Safety boundary

The added backend adapter is read-only:

- no writer, mutation route, `os` file operation, or persistence API;
- no HTTP client, WebSocket, Binance/exchange client, credential, secret, token, or order logic;
- no `learner_qualification` import or candidate-registry/lifecycle operation;
- no promotion, paper-activation, or execution-authority field/control.

The returned/rendered evidence remains constrained to:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

## Strict TDD evidence

### API vertical RED → GREEN

A complete real persisted chain fixture was added first. It builds:

```text
metric evaluation run
→ observed-only metric quality review
→ metric-quality policy decision
→ immutable qualification evidence
```

The first route test failed before implementation because `create_app()` did not accept the explicit metric-quality path configuration:

```text
TypeError: create_app() got an unexpected keyword argument
'learner_metric_evaluation_path'
```

After adding the narrow adapter, configuration, and GET route:

```text
1 passed in 1.08s
```

### Frontend model RED → GREEN

The Learner model test was added before frontend mapping. It expected separate source decision, qualification result, policies, gates, window count, hashes, and explicit safety fields. The test failed because the new view-model field did not exist.

After typed API contracts, fetch aggregation, and deterministic mapping:

```text
11 passed
```

### API regressions

`tests/unit/test_learner_api.py` now verifies:

1. real full-chain evidence returns `200` only after verification;
2. exact source files remain byte-identical after the GET;
3. returned source decision is `passed` while qualification result is `qualified`;
4. cached-only / no-exchange / unpromoted / paper-off / execution-off safety fields remain intact;
5. configured missing evidence returns the dedicated `404` body;
6. hash-tampered persisted qualification evidence returns `503`;
7. malformed persisted source policy returns `503`;
8. `POST` returns `405`.

Frontend regressions verify endpoint inventory, typed payload aggregation, successful model mapping, and preservation of integrity-unavailable state.

## Runtime verification

An isolated, real Phase 3AD persisted evidence chain was generated through the actual test fixture writers/loaders. No production artifact was changed.

### Direct API HTTP checks

```text
GET verified evidence endpoint:       200
GET default missing configuration:    404
GET malformed source-policy fixture:  503
```

Observed response mapping:

```json
404 {"detail":"learner metric-quality qualification evidence unavailable"}
503 {"detail":"learner metric-quality qualification evidence integrity verification failed"}
```

The verified `200` response carried:

```text
source_decision=passed
decision=qualified
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
```

### Production frontend dogfood

The production `frontend/dist` build was served through a temporary same-origin proxy to the isolated API fixture. The browser had:

```text
console messages: 0
JavaScript errors: 0
```

The available evidence fixture intentionally has metadata-only synthetic dataset registry entries and no physical component artifacts. Therefore `/api/v1/dataset/components` correctly returned `503` and the existing global Learner safety gate rendered:

```text
No verified dataset is available for this scope.
```

The Phase 3AE card was **not** forced visible with mocked data. This is expected fail-closed behavior: the UI must not render learner evidence when the global data foundation cannot verify. The direct verified API result and frontend model/unit/build coverage verify the Phase 3AE contract without manufacturing a browser state.

All temporary Uvicorn/Vite/proxy processes and isolated runtime artifacts were removed after verification.

## Final verification results

### Python / static / reproducibility

```text
locked pytest -q:              280 passed in 6.02s
ruff check src tests:          All checks passed
ruff format --check src tests: 103 files already formatted
mypy src:                      Success: no issues found in 61 source files
uv lock --check:               passed
compileall src tests:          passed
git diff --check:              passed
```

### Frontend

```text
Vitest:               39 passed
oxlint:               0 warnings, 0 errors
tsc -b + Vite build:  passed
```

### Focused Phase 3AE endpoint tests

```text
4 passed in 1.41s
```

### Safety scans

```text
API adapter: credential/network/exchange/order/write/os: 0 matches
API adapter: legacy qualification/registry/lifecycle fields: 0 matches
UI mutation controls: 0 matches
Frontend metric-quality route: one GET path; no mutation method matches
```

## Explicitly deferred

- batch qualification or registry processing;
- candidate lifecycle mutation or promotion transitions;
- paper activation, testnet, or live execution;
- exchange connectivity, credentials, account APIs, or order routing;
- any policy evaluation/persistence mutation from the API/UI;
- exposing evidence while the global data foundation is unverified.
