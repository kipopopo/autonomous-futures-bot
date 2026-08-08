# Phase 3k Verification — Explicit Learner Training Evidence Orchestration

**Status: GREEN**

## Scope

Phase 3k adds one explicit, read-only research-plane orchestration boundary:

```text
verified source learner artifact
→ verified prepared learner run
→ caller-supplied trainer callback
→ immutable output learner artifact
→ immutable completed-training evidence
```

The boundary is implemented by:

```text
src/autonomous_futures/research/learner_training_pipeline.py
```

and exported through:

```text
autonomous_futures.research.execute_learner_training_with_evidence
```

## Contract verified

- All filesystem roots and relative POSIX references are supplied explicitly by the caller.
- Source learner artifact is read and model-hash verified before any prepared run is persisted.
- Source artifact binding to the testing candidate is verified before persistence.
- Prepared run identity and canonical content hash are recomputed from the supplied causal windows before persistence.
- Prepared runs use the existing immutable `write_learner_run` writer.
- Training requires the existing explicit `LearnerTrainer` callback; no default model, hidden loader, network access, exchange client, or order route was added.
- Output model bytes and learner artifact use the existing write-once/hash-verified boundary.
- Completed evidence uses the existing immutable evidence builder/writer and binds the exact run/source/output references.
- A valid existing evidence path is idempotent: it is verified and returned without invoking the trainer again.
- Invalid, missing, tampered, unsafe, or binding-inconsistent inputs fail closed.

## Safety envelope

The orchestration does not qualify, promote, activate, or execute any candidate. Existing contracts retain:

```text
learner artifact state       = testing
training metrics             = null
source                       = learner_research
data source                  = cached_only
exchange access              = false
promotion state              = unpromoted
paper activation             = false
execution authority          = false
```

The coordinator contains no authenticated exchange access, signed request, order endpoint, promotion mutation, paper activation mutation, or live execution authority.

## Tests

RED → GREEN coverage added for:

- end-to-end persistence of prepared run, output artifact, and completed evidence;
- explicit trainer callback receives the verified run and copied symbol frames;
- repeated evidence orchestration returns the verified immutable envelope without retraining;
- missing source artifact fails before prepared-run persistence.

Results:

```text
Focused Phase 3k/evidence/training/run tests: 14 passed
Full backend pytest:                         206 passed
```

## Quality gates

```text
Ruff check:                  passed
Ruff format:                 88 files already formatted
Mypy:                        no issues in 49 source files
uv lock --check:             passed
Python compileall:           passed
git diff --check:             passed
Frontend Vitest:             32 passed
Frontend lint:                passed
Frontend build:               passed
Public import smoke test:     passed
```

No remote service, VPS, authenticated exchange path, training process, promotion process, or order-routing process was started.
