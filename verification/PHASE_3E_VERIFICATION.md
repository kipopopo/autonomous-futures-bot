# Phase 3e Verification — Deterministic Prepared Learner Run Contract

**Status:** GREEN.
**Scope:** Prepared-only learner-run provenance over verified causal input windows.
No learner training, model generation, metrics, promotion, paper activation, or execution authority is introduced.

## Contract delivered

Added `src/autonomous_futures/research/learner_runs.py`:

- `LearnerRun` immutable domain contract;
- `LearnerRunState = "prepared"` only;
- `prepare_learner_run(...)` pure in-memory constructor;
- deterministic `run_hash` excluding audit-only `prepared_at`;
- exact binding to learner artifact, candidate artifact, bundle, and dataset registry;
- exact feature-ID, interval, freshness-policy, and training-window binding;
- complete learner-universe symbol coverage;
- sorted, unique input-window IDs;
- cached-only and `exchange_access=false` safety fields;
- `output_artifact_hash=None`;
- `training_metrics=None`;
- `promotion_state="unpromoted"`;
- `paper_activation=false`;
- `execution_authority=false`.

The function does not load files, call the network, invoke an exchange client, mutate input frames, train a model, or persist a run artifact.

## TDD evidence

RED was observed before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_runs'
```

Focused GREEN tests:

```text
4 passed
```

Coverage includes:

1. deterministic run content across input ordering and different `prepared_at` values;
2. explicit prepared-only/no-model/no-metrics safety state;
3. complete symbol-universe coverage;
4. learner/candidate/bundle/dataset binding rejection;
5. duplicate input-window rejection;
6. identical training-window requirement;
7. unsafe run ID rejection;
8. non-UTC timestamp rejection.

## Full verification

```text
pytest: 190 passed in 3.85s
Ruff: passed
Format: 81 files already formatted
Mypy: Success: no issues found in 45 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
secret scan: 0 findings
execution token scan: none
```

## Safety decision

This phase creates provenance for a **prepared input set only**. It must not be interpreted as:

- completed learner training;
- a generated model;
- model quality or performance evidence;
- a qualified or promoted candidate;
- paper activation;
- live readiness;
- order authority.

Learner artifact/run UI status should remain unavailable until a separate verified training/output-artifact contract exists.
