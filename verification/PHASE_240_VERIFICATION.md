# Phase 240 Verification — Complete Creator History Preflight

Date: 2026-09-03 (MYT / UTC+08:00)

Status: **COMPLETED / LOCAL-INTEGRITY-SLICE / PROVIDER-NOT-CALLED**

## Scope

Close the Phase 239 lineage-preflight gap without retrying its rejected range-family campaign. The scope is a local, read-only helper that builds a complete, verified Creator candidate-ID snapshot from all persisted candidate registries beneath one explicit history root.

```text
runtime_model=gpt-5.6-terra
runtime_provider=openai-codex
runtime_effort=Medium
base_commit=5f3435de9914dafbbb42e24d77e963d469d95578
```

No remote provider, exchange endpoint, evaluator, qualification, paper, testnet, live, or order path was called.

## Implemented contract

`collect_verified_creator_candidate_ids(history_root)` in `src/autonomous_futures/api/creator.py`:

1. requires an existing explicit history root;
2. discovers every `creator-candidate-registry.json` beneath that root in sorted order;
3. verifies each registry and each referenced candidate artifact through the existing hash-verifying reader path;
4. returns sorted, deduplicated candidate IDs for the next Creator request's forbidden snapshot;
5. fails closed on absent history, absent registries, tampered artifacts, invalid registry bindings, unsafe references, or one candidate ID bound to conflicting artifact hashes.

The helper uses the registry's parent as its artifact root. This is intentional: a history supplied to a future campaign must be a portable, self-contained registry/artifact tree. A non-portable layout fails closed rather than silently omitting historical candidates.

## TDD evidence

### RED

The initial focused test failed because the public helper did not exist:

```text
ImportError: cannot import name 'collect_verified_creator_candidate_ids'
```

The conflicting-identity contract also failed before the collision guard was restored:

```text
Failed: DID NOT RAISE CreatorCandidateRegistryIntegrityError
```

### GREEN

```text
uv run --locked pytest -q tests/unit/test_creator_api.py tests/unit/test_qualification_api.py
9 passed in 1.46s
```

Added focused coverage proves:

```text
- all registries under an explicit root contribute to a sorted snapshot;
- a tampered candidate artifact blocks the snapshot;
- a repeated candidate ID with different artifact hashes blocks the snapshot.
```

## Full verification

```text
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
uv run --locked pytest -q                           PASS (719 passed)
uv run --locked ruff check src tests                PASS
uv run --locked ruff format --check src tests       PASS (354 files)
uv run --locked mypy src                            PASS (183 source files)
uv lock --check                                     PASS
git diff --check                                    PASS
```

## Safety state

```text
provider_requests=0
remote_campaigns=0
exchange_access=false
execution_authority=false
promotion_state=unpromoted
paper_activation=false
orders=0
```

## Boundary

The Phase 239 preflight defect is closed in reusable source and test coverage. The next action would require a freshly staged exact-source campaign that consumes this helper against a complete portable history root, selects a materially different falsifiable family, and makes a new provider request. That is the next major boundary and was not crossed.

## Delivery state

The verified changes and this report are deliberately left uncommitted because no explicit commit/push instruction was given for this phase.
