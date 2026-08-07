# Phase 2h Verification — Immutable Evaluator Qualification Artifact

**Status:** GREEN.
**Scope:** Research-plane qualification evidence contract and immutable persistence only.
**Safety boundary:** no evaluator engine, exchange access, paper/live execution, promotion authority, signal generation, or order routing.

## Contract

Added:

```text
src/autonomous_futures/research/qualification_artifacts.py
```

The persisted `CreatorCandidateQualificationArtifact` binds to:

- exact `candidate_id`;
- exact `candidate_artifact_hash`;
- exact `bundle_hash`;
- exact `dataset_registry_hash`;
- evaluator run ID and evaluator version;
- decision (`rejected` or `qualified`);
- Decimal-safe metrics;
- deterministic gate results and reason codes;
- evaluated walk-forward window count;
- UTC evaluation timestamp;
- qualification content hash.

The artifact explicitly carries:

```text
promotion_state: "unpromoted"
execution_authority: false
```

Therefore `qualified` means only that the persisted evidence gates passed. It does not mean paper-promoted, live, profitable, or executable.

## Deterministic evidence rules

- qualification hash excludes the audit timestamp, matching existing immutable artifact semantics;
- metrics are sorted by `metric_id` and must be unique;
- gates are sorted by `gate_id` and must be unique;
- metric and gate Decimal values must be finite;
- a `qualified` decision requires at least one evaluated window;
- a `qualified` decision requires every gate to pass;
- a `rejected` decision preserves failed gates and zero-window evidence;
- only candidates in `testing` state may be evaluated by this builder;
- JSON persistence preserves Decimal values as strings;
- conflicting rewrites and tampering fail closed.

## TDD evidence

Initial RED result before implementation:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.qualification_artifacts'
```

Focused GREEN result:

```text
6 passed in 0.71s
```

Focused cases cover:

- deterministic hash across audit timestamps;
- explicit unpromoted/execution-off boundary;
- qualified decision rejection on failed gates;
- qualified decision rejection with zero windows;
- rejected evidence preservation;
- deterministic sorting of metrics/gates;
- Decimal JSON round-trip;
- write-once persistence;
- tamper detection;
- non-finite metric rejection.

## Persistence boundary

The public research package exports:

```text
CreatorCandidateQualificationArtifact
QualificationMetric
QualificationGateResult
build_creator_candidate_qualification_artifact
read_creator_candidate_qualification_artifact
write_creator_candidate_qualification_artifact
```

No API route or dashboard field was added in this phase. This prevents the UI from presenting evaluator output before a real evaluator produces verified persisted evidence.

## Quality gates

```text
Backend pytest: 106 passed
Frontend Vitest: 9 passed
Ruff check: passed
Ruff format: passed (53 files formatted)
Mypy: Success: no issues found in 32 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 69 files, 0 findings
oxlint: 0 warnings, 0 errors
Vite production build: passed
```

## Deferred by contract

The following remain intentionally absent:

- walk-forward analyzer implementation;
- cached-data evaluator;
- promotion or qualification CLI;
- candidate status mutation;
- evaluator API endpoint;
- paper activation;
- exchange client or order endpoint;
- live trading authority.

The next implementation slice can add a deterministic cached-only evaluator adapter, but it must consume this artifact contract and remain subject to separate qualification gates.
