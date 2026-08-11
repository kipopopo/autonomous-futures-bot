# Phase 6S Verification — causal ADX feature preflight

## Status

The causal ADX feature slice is implemented and locally verified. The planned
cached-only ADX-gated RSI qualification was **not executed** because Kainode
became unreachable over the pinned SSH connection before the temporary runner
could be synchronized or run.

No qualification result, candidate metrics, promotion, paper activation, or
remote evidence is claimed for Phase 6S.

## Feature slice

```text
feature:       adx
calculation:   Wilder-style directional movement and ADX
shift:         FeatureRef.shift (tested with shift=1)
range:         finite non-negative ADX observations
```

The feature uses only prior completed OHLC bars and preserves source-frame
immutability. It is intended for the next materially new hypothesis:

```text
long:  rsi < 30 and adx < 20
short: rsi > 70 and adx < 20
```

The production evaluator, simulator, qualification gates, and safety fields
were otherwise unchanged.

## TDD and local verification

```text
RED:     adx was not in the causal evaluator allowlist
GREEN:   test_adx_is_supported_and_uses_only_prior_bars — passed
focused feature suite: 11 passed
full locked suite:     488 passed
Ruff:                   passed
Ruff format:            passed
Mypy:                   121 source files clean
uv lock --check:        passed
git diff --check:       passed
```

## Remote blocker

Three SSH attempts to the pinned Kainode address timed out, including a simple
`printf ready` probe. Therefore:

```text
remote exact-commit sync:  unavailable
Phase 6S qualification:   not run
remote metrics:            unavailable
remote evidence root:      not created by this attempt
temporary local runner:    removed
```

The immutable Phase 6N scope and strict gates remain unchanged. No network or
exchange client was invoked by the research code; the only failed network
operation was the SSH transport needed to reach the existing research worker.

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

Recommended runtime remains `gpt-5.6-luna` via `openai-codex`, `Medium` effort.
