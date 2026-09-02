# Phase 229 Verification — bounded Creator schema-diagnostic evidence propagation

Status: `GREEN / EVIDENCE-ONLY`

## Scope

Phase 229 closes the safe local evidence gap found after Phase 228. `CreatorGenerator` already produced field/type-only schema diagnostics, but `run_creator_batch` dropped them before creating `CreatorBatchTrial`, so write-once trial evidence could not explain a `schema_rejected` result.

The slice now is:

```text
strict proposal rejection
→ safe field/type diagnostics
→ CreatorBatchTrial
→ immutable CreatorBatchTrialEvidence
```

No proposal validation rule, provider request format, model, prompt, retry policy, fallback, qualification gate, promotion rule, or execution authority was changed.

## Delivered

Modified:

- `src/autonomous_futures/research/creator_batch.py`
- `src/autonomous_futures/research/creator_batch_persistence.py`
- `tests/unit/test_creator_batch.py`
- `tests/unit/test_creator_batch_persistence.py`

The batch trial now:

- carries canonical `schema_diagnostics` separately from generic `reason_codes`;
- propagates diagnostics only from the existing typed Generator result;
- rejects non-canonical diagnostic lists;
- persists diagnostics through the existing write-once evidence writer;
- retains only field paths and error types, never untrusted values or raw provider output.

The version-1 evidence hash remains backward-compatible when diagnostics are empty, so legacy trial files written before this field existed remain readable. New non-empty diagnostics remain included in the content hash.

## TDD evidence

```text
Initial propagation test:                  RED — CreatorBatchTrial had no schema_diagnostics field
Persistence propagation test:              RED — extra input was rejected
Legacy evidence compatibility test:        RED — version-1 hash mismatch after field addition
Focused batch/persistence tests:            6 passed
Full locked pytest suite:                   710 passed
Ruff check:                                 passed
Ruff format --check:                        passed
mypy src:                                   passed
uv lock --check:                            passed
git diff --check:                           passed
```

## Safety boundary

```text
new provider requests:       0
remote campaign reruns:      0
raw provider output stored:  0
exchange access:             false
promotion state:             unpromoted
paper activation:            false
execution authority:         false
orders:                      0
```

Tests used injected/local data only. No production candidate registry, evaluation, qualification, paper, testnet, or live state was mutated.

## Campaign decision

Phase 228 `creator-batch-20260902-002` was not rerun. This change does not alter the provider request, prompt, model, or proposal schema; rerunning it would be an identical retry and would not produce new contract evidence.

The next real-provider attempt remains blocked until a separately approved, materially changed provider/schema contract or prompt/adapter change exists. Any such attempt must remain one-shot, `max_retries=0`, cached-only, evidence-only, and fail-closed.

## Boundary reached

Safe schema-diagnostic propagation and legacy evidence compatibility are complete. The unresolved boundary remains provider output conformance; no parser relaxation, fallback, retry, qualification, promotion, paper activation, testnet execution, or live execution was performed.
