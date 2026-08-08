# Phase 3g Verification — Read-only Learner Evidence API/UI

**Status: GREEN**

**Scope:** read-only Learner artifact/run evidence API and UI

**Safety boundary:** cached-only, paper-safe, no execution authority

## Delivered

- Added `GET /api/v1/learner/artifact`.
- Added `GET /api/v1/learner/run`.
- Added fail-closed learner evidence loading:
  - learner artifact JSON hash validation;
  - model SHA-256 validation through the existing artifact reader;
  - candidate registry and candidate artifact binding;
  - dataset bundle and registry binding;
  - prepared learner run canonical hash validation;
  - exact run-to-artifact binding.
- Missing persisted evidence returns HTTP `404` with an `unavailable` detail.
- Tampered, malformed, or binding-conflicting evidence returns HTTP `503`.
- No POST/PUT/PATCH/DELETE learner endpoint was added.
- Extended the read-only Learner page with:
  - artifact evidence card;
  - prepared-run provenance card;
  - `VERIFIED`, `UNAVAILABLE`, and `INTEGRITY UNAVAILABLE` states;
  - MYT/GMT+8 training-window formatting;
  - explicit `UNAVAILABLE` output-artifact and metrics fields for prepared runs;
  - visible execution-authority and paper-activation OFF boundary.
- No training trigger, metric generation, qualification, promotion, paper activation, or order route was added.

## TDD Evidence

- RED tests added before implementation in `tests/unit/test_learner_api.py`.
- API tests cover:
  - missing artifact/run evidence;
  - verified artifact response;
  - verified prepared-run response;
  - tampered artifact/model/run rejection;
  - GET-only route behavior.
- Frontend tests cover:
  - verified persisted artifact/run mapping;
  - missing evidence mapping to `unavailable`;
  - integrity failures mapping to `integrity_unavailable`;
  - fail-closed behavior without verified foundation.

## Verification Results

| Gate | Result |
|---|---:|
| Backend focused learner API tests | 5 passed |
| Backend full pytest | 198 passed |
| Frontend Vitest | 32 passed |
| Frontend lint | passed — 0 warnings, 0 errors |
| Frontend production build | passed |
| Ruff check | passed |
| Ruff format | 85 files already formatted |
| Mypy | passed — no issues in 47 source files |
| `uv lock --check` | passed |
| Python compileall | passed |
| `git diff --check` | passed |

## HTTP Dogfood

Runtime was exercised over HTTP, not `file://`:

```text
GET http://127.0.0.1:8000/health
200 OK
{"status":"ok","paper_safe":true,"execution_authority":false}

GET http://127.0.0.1:8000/api/v1/learner/artifact
404 Not Found
{"detail":"learner artifact unavailable"}

GET http://127.0.0.1:8000/api/v1/learner/run
404 Not Found
{"detail":"learner run unavailable"}
```

The built frontend was also served over HTTP. With the repo's default paths, the UI correctly remained in the global `NO VERIFIED DATA` state because no dataset catalog/artifacts are present. No fake learner artifact, run, metric, or activity was created to force a success screen.

## Safety Assertions

The exposed learner models preserve:

```text
state="testing"
status="prepared"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
output_artifact_hash=null
training_metrics=null
```

Phase 3g is evidence/readiness only. It does not imply that a learner has been trained, qualified, promoted, paper-activated, profitable, or executable.
