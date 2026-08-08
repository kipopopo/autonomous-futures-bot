# Phase 3l Verification — Read-only Completed-training Evidence API/UI

**Date:** 2026-08-08
**Status:** GREEN
**Scope:** expose persisted completed-training provenance through a read-only API and dashboard surface.

## Plain-language outcome

The system can now show a **training completion proof** when all linked files and hashes verify. In simple terms, the proof says:

> An explicitly supplied trainer produced non-empty model bytes, those bytes were saved as an immutable artifact, and the saved evidence still matches the prepared run and source learner artifact.

The dashboard labels this as:

```text
COMPLETED — PROVENANCE ONLY
```

That wording is deliberate. It does **not** mean the model is accurate, profitable, qualified, promoted, paper-active, or allowed to trade.

## Implemented

- Added `GET /api/v1/learner/training-evidence`.
- Added explicit evidence and artifact-root configuration:
  - `AFBOT_LEARNER_TRAINING_EVIDENCE_PATH`
  - `AFBOT_LEARNER_TRAINING_ARTIFACT_ROOT`
- Reused the existing persisted-run, artifact, model-hash, candidate-binding, and evidence verifiers.
- Missing evidence maps to `404` / unavailable.
- Malformed, tampered, missing-linked, or binding-invalid evidence maps to `503` / integrity unavailable.
- Added a read-only dashboard card named **Training completion proof**.
- Dashboard displays output/evidence hashes, model version/family, recorded MYT/GMT+8 time, and the plain-language safety limitation.
- Added explicit unavailable and integrity-unavailable frontend states.
- Added no mutation route, training trigger, progress meter, metrics fabrication, promotion control, paper activation, or order control.

## Tests and gates

- Focused API tests: `10 passed`.
- Full backend tests: `210 passed`.
- Frontend Vitest: `33 passed`.
- Frontend lint: passed, `0 warnings`, `0 errors`.
- Frontend production build: passed.
- Ruff check: passed.
- Ruff format: passed.
- Mypy: passed.
- `uv lock --check`: passed.
- `compileall`: passed.
- `git diff --check`: passed.
- HTTP dogfood against a running Uvicorn process:

```text
GET /api/v1/learner/training-evidence
HTTP 404
{"detail":"learner training evidence unavailable"}
```

The 404 is expected for the default runtime because no completed evidence file is installed. The endpoint is present and fails closed rather than inventing a completed result.

## Not implemented in Phase 3l

- No model-quality evaluation.
- No accuracy, loss, feature-importance, or profitability claim.
- No qualification or promotion decision.
- No paper activation.
- No live activation.
- No exchange credentials or authenticated exchange access.
- No signed requests, order endpoints, execution authority, or automatic trading.
- No default trainer or hidden training scheduler.

## Safety boundary

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```
