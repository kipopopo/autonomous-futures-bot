# Phase 230 Verification — bounded Creator provider-metadata evidence propagation

Status: `GREEN / EVIDENCE-ONLY`

## Scope

Phase 230 closes the next local evidence gap after Phase 229. `CreatorGenerator` already retained an allowlisted provider metadata subset, but `run_creator_batch` discarded it before creating `CreatorBatchTrial`. The write-once trial evidence therefore lost safe transport diagnostics for provider failures.

The bounded slice is:

```text
provider failure
→ allowlisted provider metadata
→ CreatorGenerationResult
→ CreatorBatchTrial
→ immutable CreatorBatchTrialEvidence
```

No provider request format, model, prompt, proposal schema, retry policy, fallback, qualification gate, promotion rule, or execution authority changed.

## Delivered

Modified:

- `src/autonomous_futures/research/creator_batch.py`
- `src/autonomous_futures/research/creator_batch_persistence.py`
- `tests/unit/test_creator_batch.py`
- `tests/unit/test_creator_batch_persistence.py`

The batch trial now:

- carries the already-sanitized provider metadata from the typed Generator result;
- preserves metadata across rejected, duplicate, and accepted trial construction paths;
- persists non-empty metadata through the existing immutable evidence writer;
- keeps arbitrary metadata such as `secret` out of the batch result because filtering remains at the Generator boundary.

Empty provider metadata is excluded from the compatibility hash so legacy version-1 trial evidence remains readable. Non-empty metadata remains included in the content hash, and mutation is rejected on readback.

## TDD evidence

```text
Initial propagation/tamper tests:           RED — 2 failed, 6 passed
Focused Creator generator/batch/persistence: 15 passed
Full locked pytest suite:                    712 passed
Ruff check:                                  passed
Ruff format --check:                         passed
mypy src:                                    passed
uv lock --check:                             passed
git diff --check:                            passed
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

All tests used injected/local data. No production candidate registry, evaluation, qualification, paper, testnet, or live state was mutated.

## Campaign decision

Phase 228 `creator-batch-20260902-002` was not rerun. This is metadata-only evidence propagation and does not change the provider request, prompt, model, or proposal schema. An identical real-provider retry remains unjustified.

The next real-provider attempt remains blocked until a separately approved, materially changed provider/schema contract or prompt/adapter change exists. Any future attempt must remain one-shot, `max_retries=0`, cached-only, evidence-only, and fail-closed.

## Boundary reached

Safe provider-metadata propagation and hash-bound persistence are complete. The unresolved boundary remains provider output conformance; no parser relaxation, fallback, retry, qualification, promotion, paper activation, testnet execution, or live execution was performed.
