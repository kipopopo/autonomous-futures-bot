# Phase 235 Verification — Trusted Local Candidate Identity

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **GREEN / LOCAL-CONTRACT / EVIDENCE-ONLY**

## Scope

Replace provider-controlled Creator candidate identity with deterministic identity assigned at the existing local proposal-intake boundary.

This phase does not run a provider campaign or change evaluation, qualification, promotion, paper, testnet, live, exchange, or order authority.

## Root cause

Phase 234 proved that a structurally valid provider response could be discarded because the provider repeated a historical `strategy_id`. Requiring a remote model to author globally unique lineage identity made an untrusted field authoritative.

Changing only the provider-authored ID could also bypass semantic duplicate detection while leaving the strategy unchanged.

## Contract

After strict `CreatorProposal` validation, local intake now computes:

```text
candidate_id = "cand-" + sha256(canonical StrategySpec excluding strategy_id)
```

Properties:

- the provider's `strategy_id` remains a schema-validated placeholder;
- provider-authored identity is replaced before forbidden-lineage checks;
- identical strategy semantics receive the same candidate ID even when the provider changes its placeholder ID;
- materially changed strategy content receives a different candidate ID;
- proposal hashing binds the locally canonicalized strategy;
- existing persisted historical evidence is not rewritten;
- raw prompts and raw provider responses remain absent.

The revision prompt now asks for a material strategy change and states that changing only `strategy_id` does not create a new candidate.

## Strict TDD evidence

RED:

```text
uv run --locked pytest -q tests/unit/test_creator_generator.py -k local_candidate_id
1 failed, 6 deselected
expected=rejected
observed=accepted
```

The failing check used the same strategy under a different provider-authored ID and proved that the old boundary could bypass a forbidden candidate ID.

GREEN focused suite:

```text
38 passed in 1.11s
```

Covered files:

```text
tests/unit/test_creator_generator.py
tests/unit/test_creator_proposals.py
tests/unit/test_creator_batch.py
tests/unit/test_creator_prompts.py
tests/unit/test_google_ai_studio_provider.py
```

The focused lineage check confirms that a changed provider placeholder maps to the same local candidate ID and is rejected when that canonical ID is forbidden.

## Full verification

```text
uv run --locked pytest -q
715 passed in 8.25s

uv run --locked ruff check src tests
All checks passed!

uv run --locked ruff format --check src tests
354 files already formatted

uv run --locked mypy src
Success: no issues found in 183 source files

uv lock --check
PASS

git diff --check
PASS
```

## Safety state

```text
provider_requests=0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
historical_evidence_rewritten=false
```

## Boundary

Phase 235 closes the candidate-identity architecture decision locally. It does not authorize another provider request. Any campaign remains a separate bounded, exact-source, cached-only operation with independent immutable readback and zero retry/fallback.
