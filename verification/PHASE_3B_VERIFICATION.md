# Phase 3b Verification — Immutable Learner Artifact Contract

**Status:** GREEN.
**Scope:** Backend-only immutable contract for a future cached-only learner
artifact. No learner training, API route, dashboard mutation, paper activation,
promotion, or execution authority was added.

## Contract

`LearnerArtifact` is a typed, persisted provenance envelope that binds a future
learner model artifact to:

- exact Creator candidate ID and candidate artifact hash;
- exact bundle hash;
- exact dataset-registry hash;
- candidate symbols and fixed `5m`/`15m` interval contract;
- learner run and learner version;
- model family and sorted unique feature IDs;
- UTC half-open training window;
- relative POSIX model artifact reference;
- SHA-256 of the referenced model file.

Required safety fields are immutable:

```text
state="testing"
source="learner_research"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The contract does not claim that a learner model exists in the repository. A
real model file must be supplied explicitly by a future learner pipeline before
`write_learner_artifact(...)` can persist its envelope.

## TDD

Added `tests/unit/test_learner_artifacts.py`.

RED was confirmed before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_artifacts'
```

Focused GREEN result:

```text
5 passed
```

Coverage includes:

1. deterministic content hash across different audit timestamps;
2. testing-only state and non-authoritative safety fields;
3. exact candidate/dataset/symbol/interval binding;
4. UTC training window ordering;
5. relative POSIX path and traversal rejection;
6. model-file SHA-256 verification;
7. learner JSON hash tamper detection;
8. model file tamper detection;
9. missing model rejection;
10. atomic write-once and conflicting rewrite rejection.

## Implementation

Added:

- `src/autonomous_futures/research/learner_artifacts.py`
  - `LearnerArtifact` contract;
  - deterministic content hashing excluding only `created_at` and `artifact_hash`;
  - candidate-binding verification;
  - model-root containment and model-file hash verification;
  - atomic write-once persistence;
  - fail-closed reads.
- public exports in `src/autonomous_futures/research/__init__.py`.

A conflicting rewrite is checked against the existing learner JSON integrity
before external model-root verification, ensuring immutable conflict behavior is
stable and not dependent on a caller-supplied root.

No learner artifact/model file was generated under the repository. No candidate,
registry, qualification artifact, promotion state, paper state, or exchange
state was changed.

## Verification

```text
Backend pytest: 177 passed in 3.59s
Focused learner tests: 5 passed
Ruff check: passed
Ruff format --check: 75 files already formatted
Mypy: Success, no issues found in 42 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Changed-file credential scan: 0 findings
Execution/order token scan: none
```

Frontend/browser verification was not repeated because Phase 3b is a backend-only
domain contract and does not modify frontend code or API routes.
