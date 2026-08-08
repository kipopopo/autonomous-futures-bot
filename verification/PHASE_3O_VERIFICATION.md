# Phase 3o Verification — Immutable learner qualification evidence boundary

**Status:** GREEN
**Scope:** Convert verified learner holdout observations into deterministic, immutable qualification evidence without changing candidate state or granting execution authority.

## Bahasa mudah

Phase 3o menambah pagar yang menjawab soalan berikut:

> “Berdasarkan evidence holdout yang sudah diverifikasi dan policy yang ditetapkan secara explicit, adakah semua gate yang diperlukan lulus?”

Jawapan yang disimpan hanya:

- `qualified` — semua gate evidence lulus; atau
- `rejected` — sekurang-kurangnya satu gate gagal atau evidence tidak mencukupi.

`qualified` di sini bermaksud **evidence gates passed sahaja**. Ia bukan bermaksud model profitable, model bagus, paper-live, promoted atau boleh menghantar order.

Jika metric yang diperlukan hilang, nilai tidak finite, window tidak cukup, binding berubah atau evidence hash rosak, sistem tidak meneka. Ia reject/fail closed.

## Implemented

### Contract

Added `src/autonomous_futures/research/learner_qualification.py` dengan:

- explicit `LearnerQualificationPolicy`;
- per-metric comparator `gte`, `lte` atau `eq`;
- minimum holdout-window gate;
- Decimal-safe finite thresholds dan observations;
- deterministic sorted metric/gate evidence;
- `qualified` / `rejected` decision;
- deterministic policy and evidence SHA-256 hashes;
- UTC audit timestamp.

### Provenance and integrity

Qualification evidence binds:

- completed-training evidence ID/hash;
- quality-review ID/hash;
- output learner artifact hash;
- learner/run identity;
- candidate artifact, bundle and dataset registry hashes;
- exact policy ID/hash.

Before building evidence, the boundary verifies training evidence, quality-review hash/conclusion, output-artifact-to-candidate binding, and all provenance fields.

### Persistence

- write-once immutable JSON envelope;
- atomic exclusive file creation;
- identical writes are idempotent;
- conflicting rewrites are rejected;
- malformed/tampered/hash-mismatched reads fail closed;
- Decimal values remain exact JSON strings.

### Safety envelope

Every artifact preserves:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

No candidate registry, candidate artifact, learner artifact, model state or lifecycle state is mutated.

No API/UI route, promotion action, paper activation, live adapter or order endpoint was added in this phase.

## TDD evidence

The new focused test initially failed at collection because the qualification module did not exist. After the minimum implementation:

```text
Phase 3o focused tests: 6 passed
Related learner/quality/API tests: 23 passed
```

Coverage includes:

- deterministic qualified evidence;
- rejected evidence with failed-window preservation;
- missing metric and insufficient-window fail-closed behavior;
- binding drift rejection;
- Decimal JSON round-trip;
- immutable/idempotent persistence;
- tamper detection;
- non-finite and duplicate policy rejection;
- explicit no-authority safety fields.

## Verification gates

```text
Full backend suite: 223 passed in 6.54s
Ruff check: All checks passed!
Ruff format: 92 files already formatted
Mypy: Success: no issues found in 51 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
source/test safety scan: 0 findings
```

## Not implemented by design

- no model-quality claim;
- no profitability claim;
- no automatic qualification-to-promotion transition;
- no candidate status mutation;
- no paper activation;
- no shadow/demo activation;
- no live trading;
- no authenticated exchange access;
- no order placement, cancellation or routing;
- no hidden reviewer, trainer or network loader.

The next separate boundary, if approved later, would be read-only visibility for persisted learner qualification evidence. It must remain observational until the project has real, reproducible model-quality research and explicit downstream governance gates.
