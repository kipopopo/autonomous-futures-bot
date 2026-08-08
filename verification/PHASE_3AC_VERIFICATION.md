# Phase 3AC Verification — Immutable Metric-Quality Qualification Evidence

## Status

**GREEN — Phase 3AC scope verified locally.**

Phase 3AC makes the Phase 3AB in-memory metric-quality qualification evidence durable as an independent, immutable artifact:

```text
verified metric evaluation
→ verified observed-only metric-quality review
→ verified persisted metric-quality decision
→ in-memory qualification input
→ in-memory qualification evidence
→ immutable persisted qualification evidence
```

It does **not** add a verified persisted full-chain loader, API/UI endpoint, candidate lifecycle mutation, promotion, paper activation, exchange access, or execution authority.

## Model-tier decision

Runtime used:

```text
model: gpt-5.6-terra
provider: openai-codex
```

This bounded persistence and integrity phase reuses established typed evidence, canonical-hash, atomic-link, and strict-TDD patterns. `terra` was suitable; no silent model routing occurred.

## Delivered API

In `src/autonomous_futures/research/learner_metric_quality_qualification.py`:

```python
read_learner_metric_quality_qualification_evidence(path)
write_learner_metric_quality_qualification_evidence(path, evidence)
```

Both are exported through `autonomous_futures.research`.

### Read behavior

The reader:

1. reads UTF-8 typed JSON;
2. maps unavailable paths to `FileNotFoundError`;
3. maps malformed JSON/model shape to `DataQualityError`;
4. recomputes the canonical qualification SHA-256;
5. fails closed on hash drift with `DomainViolation`;
6. returns only verified typed evidence.

### Write behavior

The writer:

1. verifies the caller-supplied qualification hash **before any filesystem work**;
2. validates an existing destination through the shared reader;
3. accepts only an exactly identical existing artifact as idempotent;
4. rejects any conflict, including changed `evaluated_at` despite equal content hash;
5. serializes deterministic sorted-key JSON with a final newline;
6. writes through a unique sibling UUID temporary file;
7. publishes exclusively through `os.link`;
8. verifies a race winner before accepting it;
9. removes temporary files in `finally`, including generic link failures;
10. readbacks and hash-verifies the published artifact before return.

## Immutable semantics

Canonical qualification hashes exclude only:

```text
evaluated_at
qualification_hash
```

Therefore two equivalent records at distinct audit times keep the same content hash, but cannot overwrite the same immutable destination path. The full typed evidence remains different and the writer correctly rejects the collision.

Both `qualified` and `rejected` evidence may become durable audit records. A rejected record is preserved as evidence; it is never treated as unavailable or replaced with fabricated values.

## Safety boundary

The persistence contract remains separate from qualification construction and all authority layers. The persisted model still enforces:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The Phase 3AC module has no credential handling, network/HTTP/exchange client, order route, candidate registry access, creator/learner artifact writer, existing `learner_qualification` module usage, promotion transition, paper activation, or execution call.

Persisting `qualified` evidence is **not** promotion, paper permission, profitability proof, or execution permission.

## Strict TDD evidence

### RED

Before the reader/writer implementation, the new vertical persistence test failed during collection:

```text
ImportError:
  cannot import name
  'read_learner_metric_quality_qualification_evidence'
exit code: 4
```

This was the expected missing persistence API failure.

### GREEN

After implementing the smallest typed reader/writer, the same vertical test passed:

```text
1 passed in 2.01s
```

### Added focused coverage

`tests/unit/test_learner_metric_evaluation.py` covers:

1. qualified evidence atomic write/read round trip;
2. identical-write idempotency;
3. audit-timestamp conflict at an occupied immutable path;
4. missing, malformed, and tampered evidence failure mapping;
5. caller hash mismatch before any destination-parent creation;
6. UUID temporary-file cleanup after generic `os.link` failure;
7. durable round trip for rejected evidence;
8. preserved safety fields and pre-existing full-chain qualification provenance tests.

## Verification results

### Focused

```text
43 passed in 4.67s
```

### Related provenance regression

```text
72 passed in 4.95s
```

Coverage includes metric evaluation, metric review/decision, Phase 3AB qualification, existing learner qualification, learner review, training evidence, learner evaluation, and learner-run contracts.

### Full locked suite

```text
271 passed in 15.46s
```

### Static and reproducibility gates

```text
ruff check: All checks passed
ruff format --check: 101 files already formatted
mypy src: Success: no issues found in 59 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
```

### Safety scan

```text
credentials / secrets / tokens: 0 findings
HTTP / exchange client / order route: 0 findings
candidate registry / lifecycle writer / learner_qualification import: 0 findings
```

The only authority-state declarations are the required fixed safe values:

```text
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

### Browser verification

Not applicable: this is a backend-only persistence contract. No API, UI, HTTP, or frontend asset changed.

## Explicitly deferred

- Phase 3AD verified persisted qualification-evidence full-chain loader;
- qualification API/UI exposure;
- candidate lifecycle mutation;
- promotion;
- paper activation;
- testnet/live execution;
- exchange connectivity and order routing.
