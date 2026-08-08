# Phase 3p Verification — Read-only Learner Qualification Evidence API/UI

**Status:** GREEN (automated gates passed; full backend network dogfood limited by local dependency environment)

## Scope

Phase 3p exposes persisted learner qualification evidence through a read-only API and Learner UI surface. The implementation does not create qualification decisions, promote candidates, activate paper trading, or provide execution authority.

## Layman summary

### Sudah dibuat

- Learner qualification evidence boleh dibaca melalui `GET /api/v1/learner/qualification`.
- API tidak menerima keputusan hanya kerana fail qualification wujud. Ia verify semula chain:
  - learner artifact dan candidate binding;
  - completed-training evidence;
  - output artifact hash;
  - quality-review evidence;
  - explicit persisted qualification policy;
  - qualification evidence hash dan exact bindings.
- Learner page memaparkan `QUALIFIED` atau `REJECTED` hanya apabila evidence telah verified.
- UI menunjukkan metric observations, gate results, policy hash dan qualification hash sebagai audit evidence.
- UI sentiasa melabel decision sebagai `EVIDENCE ONLY — NOT PROMOTION`.
- Evidence yang hilang atau integrity-invalid dipaparkan sebagai unavailable; sistem tidak meneka nilai atau decision.

### Belum dibuat

- Model quality research penuh atau trainer ML sebenar.
- Automatic promotion atau manual promotion authority.
- Paper activation, live activation atau order routing.
- Authenticated exchange access.
- Pengubahan candidate state melalui API/UI.

## Technical implementation

### Backend

- `src/autonomous_futures/research/learner_qualification.py`
  - added strict read/validation of explicit qualification policy JSON;
  - invalid policy fails closed with `DomainViolation`.
- `src/autonomous_futures/api/learner.py`
  - added `load_verified_learner_qualification_evidence(...)`;
  - verifies policy, training evidence, output artifact, quality review and final qualification evidence;
  - missing evidence maps to unavailable;
  - malformed, tampered, missing dependency or binding-inconsistent evidence maps to integrity failure.
- `src/autonomous_futures/api/app.py`
  - added `LearnerQualificationEvidenceResponse`;
  - added `GET /api/v1/learner/qualification`;
  - added explicit configuration paths:
    - `AFBOT_LEARNER_QUALIFICATION_EVIDENCE_PATH`
    - `AFBOT_LEARNER_QUALIFICATION_POLICY_PATH`
  - defaults are `data/learner-qualification-evidence.json` and `data/learner-qualification-policy.json`.

### API behavior

| Request | Result |
|---|---|
| `GET /api/v1/learner/qualification` with verified chain | `200`, `verified: true`, evidence payload |
| Qualification evidence missing | `404`, `learner qualification unavailable` |
| Hash/policy/binding/dependency integrity failure | `503`, `learner qualification integrity verification failed` |
| `POST /api/v1/learner/qualification` | `405` |

### Frontend

- Added typed qualification response, metric and gate models.
- Added qualification fetch to the dashboard read-only data path.
- Added view-model states:
  - `verified`;
  - `unavailable`;
  - `integrity_unavailable`.
- Added Learner qualification evidence card with responsive styling.
- No promote, activate, trade, order or mutation controls were added.
- Updated `frontend/design-system/pages/learner-readiness.md` with the evidence-only boundary.

## TDD and automated verification

### RED → GREEN

- Added backend regression coverage for:
  - verified qualification response;
  - missing evidence;
  - tampered qualification hash;
  - valid-hash binding drift;
  - immutable source-byte preservation;
  - GET-only behavior.
- Added frontend regression coverage for:
  - verified qualification mapping;
  - integrity-unavailable mapping;
  - qualification API fetch path.

### Results

- Focused learner/API/qualification/quality suites: **26 passed**.
- Full backend suite: **226 passed in 5.64s**.
- Ruff check: **All checks passed!**
- Ruff format: **92 files already formatted**.
- Mypy: **Success: no issues found in 51 source files**.
- `uv lock --check`: passed.
- `compileall`: passed.
- `git diff --check`: passed.
- Frontend tests: **37 passed**.
- Frontend lint: **0 warnings, 0 errors**.
- Frontend production build: passed.
- Changed-diff safety scan: **0 findings** for credential, signed-request, order, `execution_authority=true`, or `paper_activation=true` patterns.

## Dogfood boundary

- Vite Learner route was exercised over HTTP at `http://127.0.0.1:8767/?dogfood=phase3p-unavailable#/learner`.
- Browser console errors: **0**.
- Browser verification confirmed fail-closed unavailable state, no fake qualification, and no promotion controls.
- Network Uvicorn fixture dogfood was not claimed as passed because this host has an environment mismatch:
  - system Python 3.11 has compatible NumPy/Pandas but lacks `pyarrow`;
  - project `.venv` is Python 3.14 while its NumPy binary is CPython 3.11.
- The actual FastAPI route and response mapping were nevertheless exercised through the full learner API test suite using the production app and persisted fixtures. No dependency was installed or silently changed to mask the runtime limitation.
- All temporary fixture and server processes were removed/stopped.

## Safety boundary

```text
promotion_state = "unpromoted"
paper_activation = false
execution_authority = false
```

Qualification evidence means only that explicit evidence gates were recorded as passed or rejected. It does not mean profitable, promoted, paper-live, live, or executable.
