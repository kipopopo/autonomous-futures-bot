# Phase 2f Verification — Immutable Creator Candidate Contract

**Status:** GREEN.
**Scope:** Research-plane contract and immutable registry only.
**Safety boundary:** no candidate generation engine, no evaluator, no signal, no account state, no sizing/leverage, no order routing, and no promotion authority were added.

## Contract delivered

Added `src/autonomous_futures/research/creator_artifacts.py` and the research package export:

- `CreatorCandidateArtifact` — typed strategy artifact bound to exact dataset bundle and dataset-registry hashes;
- `CreatorCandidateRegistryEntry` — metadata-only artifact reference and provenance record;
- `CreatorCandidateRegistry` — deterministic sorted registry with its own content hash;
- atomic write-once JSON persistence and hash-verified readback;
- conflicting rewrites and tampered JSON fail closed;
- relative POSIX artifact references reject absolute paths and traversal;
- candidate identity must equal `StrategySpec.strategy_id`;
- strategy universe symbols must be sorted and unique;
- one registry cannot mix dataset bundle/registry bindings;
- initial state is restricted to `testing`.

Audit timestamps are retained but excluded from artifact/registry identity hashes. The contract contains no order intent, quantity, leverage, margin, account, or exchange credential fields.

## TDD evidence

### RED

Initial focused collection failed because the research contract did not exist:

```text
ModuleNotFoundError: No module named 'autonomous_futures.research'
exit code: 2
```

The mixed-dataset-binding tracer then failed before its implementation:

```text
Failed: DID NOT RAISE DataQualityError
```

### GREEN

Focused contract suite:

```text
7 passed in 0.59s
```

Covered behaviors:

- deterministic artifact hash across audit timestamps;
- default `testing` state;
- strategy/candidate identity binding;
- artifact write-once and tamper detection;
- sorted registry and exact lookup;
- mixed dataset binding rejection;
- registry write-once and tamper detection;
- path traversal rejection.

## Bounded dogfood

A deterministic contract fixture was persisted and read back through the production writers/readers inside a temporary directory. No fixture was committed or exposed through the dashboard.

```json
{
  "artifact_hash": "e5f388228f175587eef21cbe9967e11487007caebfacf40876801f7e648eb1e3",
  "registry_hash": "2955c99518d11d6a741dcdc32eb91cbd35b9bfd41091ecdf954dd230fee277ca",
  "candidate_id": "cand-dogfood-001",
  "state": "testing",
  "artifact_readback": true,
  "registry_readback": true,
  "temporary_cleanup": true
}
```

This proves contract persistence and integrity behavior only. It is not a research-quality result and does not represent an admitted or promoted strategy.

## Quality gates

```text
Focused pytest: passed
Ruff check: passed
Ruff format --check: passed
Mypy for research package: passed
```

Full regression and post-commit verification remain required before delivery.
