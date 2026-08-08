# Phase 2s Verification — Persisted Candidate Registry Batch Qualification

**Status:** GREEN.
**Scope:** Deterministic batch qualification over a persisted candidate registry.
**Safety boundary:** read-only candidate/registry inputs; qualification evidence
writes only; no lifecycle mutation, promotion, paper activation, order routing,
or execution authority.

## Added contract

```text
src/autonomous_futures/research/persisted_qualification.py
src/autonomous_futures/research/__init__.py
tests/unit/test_persisted_qualification_batch.py
```

New public contracts:

```text
PersistedQualificationBatchFailure
PersistedQualificationBatchResult
run_persisted_qualification_batch(...)
```

## Batch flow

```text
read and hash-verify candidate registry
→ select persisted entries in testing state
→ apply deterministic optional candidate limit
→ resolve each candidate artifact_ref safely under its root
→ verify candidate identity/hash/dataset binding against registry entry
→ resolve that candidate's explicit OOS aggregation ref
→ verify aggregation envelope/hash
→ build strict pooled/per-symbol qualification evidence
→ write only that candidate's immutable qualification artifact
→ return stable machine-readable batch result
```

Candidates are processed in registry order. Each candidate receives its own
aggregation reference and qualification output path. No aggregate evidence is
reused between candidates.

## Batch result semantics

`PersistedQualificationBatchResult` keeps partitions explicit:

```text
selected_candidate_ids
unselected_candidate_ids
evaluated_candidate_ids
qualified_candidate_ids
rejected_candidate_ids
blocked_candidate_ids
failures
```

The result validator enforces sorted unique IDs and disjoint partition
invariants. A `qualified_candidate_ids` entry means qualification evidence
passed; it is not a promoted ID.

Safety fields are fixed:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
execution_authority=false
```

## Fail-closed behavior

Stable blocked reason codes cover:

```text
missing_candidate_artifact
candidate_artifact_hash_mismatch
candidate_registry_binding_mismatch
invalid_candidate_artifact
missing_persisted_aggregation
aggregation_hash_mismatch
candidate_aggregation_binding_mismatch
invalid_persisted_aggregation
qualification_artifact_conflict
```

One blocked candidate does not cause another candidate's valid evidence to be
silently reused or skipped. Valid candidates continue independently; blocked
candidates produce no qualification artifact.

The optional `limit` is a candidate limit only. It does not alter candle or
OOS aggregation evidence. Entries outside the limit are returned explicitly as
`unselected_candidate_ids`.

## Persistence safety

The batch runner never writes:

```text
candidate artifact
candidate registry
candidate lifecycle state
promotion state
execution authority
```

It writes only per-candidate qualification evidence through the existing
atomic/write-once writer. Existing conflicting or malformed qualification
files are blocked and preserved unchanged.

## TDD evidence

Initial RED:

```text
ImportError:
cannot import name 'PersistedQualificationBatchResult'
```

Focused GREEN:

```text
Persisted batch tests: 6 passed
```

Tests cover:

- independent candidate-specific qualification;
- one candidate qualifying while another is rejected by drawdown;
- missing aggregation blocking without output artifact;
- tampered candidate blocking while another candidate continues;
- deterministic candidate limit and explicit unselected IDs;
- conflicting existing qualification artifact blocking without overwrite;
- non-positive limit rejection;
- candidate bytes and registry preservation.

## Quality gates

```text
Backend pytest: 166 passed
Focused batch qualification tests: 6 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (69 files formatted)
Mypy: Success: no issues found in 39 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 116 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- candidate status transition;
- promotion or paper activation;
- a command-line interface;
- API/UI exposure;
- live/testnet execution;
- funding, leverage, margin, or liquidation accounting;
- profitability beyond the supplied deterministic OOS evidence.
