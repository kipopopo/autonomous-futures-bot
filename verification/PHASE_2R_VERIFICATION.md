# Phase 2r Verification — Persisted Candidate Qualification Flow

**Status:** GREEN.
**Scope:** Persisted candidate + persisted OOS aggregation read/write flow.
**Safety boundary:** qualification evidence only; no candidate mutation,
promotion, paper activation, order routing, or execution authority.

## Added contract

```text
src/autonomous_futures/research/walk_forward.py
src/autonomous_futures/research/persisted_qualification.py
src/autonomous_futures/research/__init__.py
tests/unit/test_persisted_qualification.py
```

New persisted aggregation contract:

```text
PersistedWalkForwardAggregation
build_persisted_walk_forward_aggregation(...)
read_walk_forward_aggregation(...)
write_walk_forward_aggregation(...)
walk_forward_aggregation_hash(...)
```

New persisted qualification flow:

```text
qualify_persisted_candidate(...)
```

## Flow

```text
read_creator_candidate_artifact()
  → verify candidate artifact hash and testing state
read_walk_forward_aggregation()
  → validate typed aggregation envelope and aggregation hash
build_walk_forward_qualification_artifact()
  → strict pooled/per-symbol policy gates
write_creator_candidate_qualification_artifact()
  → atomic/write-once qualification evidence
```

The flow performs no write to the candidate artifact or candidate registry.
The only output write is the immutable qualification artifact.

## Persistence integrity

Persisted OOS aggregation is wrapped with a deterministic canonical hash:

```text
aggregation_hash = SHA-256(canonical WalkForwardAggregation JSON)
```

Readback fails closed on:

- aggregation hash mismatch;
- malformed persisted aggregation;
- invalid typed aggregation content.

Hash failures are normalized to `DomainViolation` at the persistence boundary.

Existing qualification artifact write-once behavior is used unchanged:

- identical artifact rewrite returns the existing artifact;
- conflicting rewrite raises `DomainViolation`;
- writes use a temporary sibling followed by atomic replacement.

## Safety behavior

The persisted flow preserves:

```text
candidate.state="testing"
qualification.source="walk_forward_oos"
qualification.promotion_state="unpromoted"
qualification.execution_authority=false
```

A passing qualification artifact remains evidence only. It does not modify
candidate state and does not authorize paper, testnet, or live execution.

Rejected evidence is persisted with its failed gates and reason codes rather
than being discarded.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.persisted_qualification'
```

Focused GREEN:

```text
Persisted qualification tests: 4 passed
```

Tests cover:

- persisted aggregation envelope read/write and hash binding;
- qualified flow writes evidence without mutating candidate bytes/state;
- rejected evidence remains persisted;
- identical persisted rerun is idempotent;
- tampered candidate artifact fails closed;
- tampered aggregation artifact fails closed;
- conflicting qualification rewrite is rejected.

## Quality gates

```text
Backend pytest: 160 passed
Focused persisted qualification tests: 4 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (68 files formatted)
Mypy: Success: no issues found in 39 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 114 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- candidate registry status updates;
- promotion or paper activation;
- a qualification CLI;
- API/UI exposure of qualification evidence;
- live/testnet execution;
- funding, leverage, margin, or liquidation accounting;
- profitability beyond the supplied deterministic OOS metrics.
