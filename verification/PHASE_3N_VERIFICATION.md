# Phase 3n Verification — Read-only quality-review evidence API/UI

**Status:** GREEN
**Scope:** Expose deterministic learner quality-review evidence through a verified read-only API and Learner dashboard card.

## Bahasa mudah

Phase 3n sekarang boleh menunjukkan bukti pemeriksaan holdout yang memang sudah disimpan:

- quality-review evidence diverifikasi bersama completed-training evidence dan output artifact;
- hash, binding, holdout window, row count dan metric pemerhatian dipaparkan;
- nilai metric dikekalkan sebagai string exact di API/UI;
- evidence yang hilang dipaparkan sebagai `UNAVAILABLE`;
- evidence yang rosak, malformed atau dependency-nya gagal diverifikasi dipaparkan secara fail-closed;
- UI menggunakan label `OBSERVED ONLY` dan tidak membuat keputusan model bagus, profitable atau boleh trade.

Phase ini **belum** melakukan model-quality research penuh, qualification, promotion, paper activation, live trading, order routing atau authenticated exchange access.

## Implemented

### Backend

- Added `GET /api/v1/learner/quality-review`.
- Added verified loader that:
  - verifies the configured completed-training evidence;
  - resolves output-artifact references inside the configured artifact root;
  - verifies the output artifact and candidate binding;
  - verifies the quality-review evidence hash and binding;
  - fails closed on missing, malformed, tampered or inconsistent evidence.
- Added explicit response model and error mapping:
  - `404 learner quality review unavailable` when review evidence is absent;
  - `503 learner quality review integrity verification failed` when evidence or required provenance cannot be verified.
- No POST, PUT, PATCH or DELETE route was added.

### Frontend

- Added quality-review API response types and loading state.
- Added view-model states: `verified`, `unavailable`, `integrity_unavailable`.
- Added read-only Learner evidence card showing:
  - review identity and version;
  - `OBSERVED ONLY` conclusion;
  - holdout windows and rows evaluated;
  - caller-reported metrics without pass/fail thresholds;
  - evidence/output hashes;
  - safety fields indicating no promotion or execution authority.
- Added unavailable and integrity-unavailable presentation.
- Updated Learner design-system documentation.

## Verification evidence

### Backend

```text
Focused API + quality-review tests: 17 passed
Full backend suite: 217 passed in 4.57s
Ruff check: All checks passed!
Ruff format: 90 files already formatted
Mypy: Success: no issues found in 50 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
```

### Frontend

```text
Frontend tests: 35 passed
Frontend lint: 0 warnings and 0 errors
Frontend production build: passed
```

### HTTP dogfood

The actual Uvicorn runtime was exercised over HTTP:

```text
GET /health                                  200
GET /api/v1/learner/quality-review           404 learner quality review unavailable
POST /api/v1/learner/quality-review           405 Allow: GET
```

The 404 is expected for the default environment because no completed quality-review evidence is present. The system did not invent evidence.

The production frontend build was served over HTTP and inspected in a browser. The Learner route rendered its unavailable foundation state, showed `EXECUTION AUTHORITY: OFF`, showed no fake metrics or quality claims, and produced no browser JavaScript errors.

Verified quality-review fixture behavior, tampered evidence behavior and GET-only behavior were covered by the backend API tests.

### Safety scan

```text
source/test safety scan: 0 findings
```

The scan found no new credential pattern, signed request, order placement/cancellation, `execution_authority=true`, `paper_activation=true` or promoted-state addition in the changed source/tests.

## Not implemented by design

- No default reviewer or hidden model loader.
- No network or exchange access from the quality-review boundary.
- No qualification decision.
- No candidate promotion.
- No paper/live activation.
- No execution authority.
- No order endpoint or authenticated exchange client.
