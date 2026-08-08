# Phase 3W Verification — Verified Persisted Learner Metric Quality-Review Input

## Status

**GREEN — Phase 3W scope verified locally.**

This phase adds a read-only handoff for persisted observed-only metric quality-review evidence:

```text
verified persisted metric evaluation run
+ verified persisted observed-only quality review
→ exact provenance and window binding verification
→ downstream evidence input
```

## Implemented

- Added `load_verified_learner_metric_quality_review(...)` in:
  - `src/autonomous_futures/research/learner_metric_quality_review_input.py`
- Reused the shared readers and metric-input verifier:
  - `load_verified_learner_metric_review_input(...)`
  - `read_learner_metric_quality_review_evidence(...)`
- Verified the full chain before returning evidence:
  - metric evaluation run ID and canonical hash;
  - learner ID and learner artifact hash;
  - creator candidate ID and candidate artifact hash;
  - bundle hash;
  - dataset-registry hash;
  - exact metric evaluation window count;
  - exact `(window_id, symbol)` identity for every window;
  - learner/candidate/window symbol membership.
- Reused `verify_learner_artifact_binding(...)` for learner/candidate integrity.
- Exported the loader from `autonomous_futures.research`.

The loader performs no writes and does not invoke a reviewer.

## Tests

Focused Phase 3W metric suite:

```text
18 passed in 2.09s
```

Related learner evidence regression:

```text
47 passed in 5.21s
```

Full backend regression:

```text
246 passed in 22.78s
```

Coverage includes:

- valid full-chain verified load;
- persisted source-byte preservation;
- candidate binding drift rejection;
- tampered review hash rejection;
- metric evaluation hash drift rejection;
- review window symbol drift rejection;
- exact run/hash and window identity assertions.

## Static and repository gates

```text
Ruff: All checks passed!
Format: 97 files already formatted
Mypy: Success: no issues found in 55 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
Safety scan for credential/network/exchange/order/promotion controls: 0 findings
```

## Safety boundary

This phase does **not**:

- recompute metrics or quality observations;
- invoke a reviewer;
- load OHLCV, model, or exchange data;
- call a network or exchange client;
- write or mutate persisted evidence;
- qualify or reject a learner;
- promote a candidate;
- activate paper or live trading;
- grant execution authority;
- add an API or frontend route.

The returned artifact remains the Phase 3U/3V observational envelope:

```text
review_conclusion="observed_only"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

## Browser dogfood

Not applicable. Phase 3W changes only backend research-domain loading and binding verification; no API or frontend files changed.

## Conclusion

Phase 3W provides a shared, verified, read-only handoff for persisted metric quality-review evidence. Downstream callers can receive evidence only after the persisted metric run, persisted review artifact, learner, candidate, and every window identity agree exactly. No quality decision or trading authority is created by this boundary.
