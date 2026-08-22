# Phase 87 Verification — Creator schema compatibility tightening

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Diagnostic evidence

One real DeepSeek request used the canonical Creator prompt and emitted only safe response-shape metadata:

```text
provider requests: 1
provider JSON received: yes
raw values logged: false
credential value logged: false
```

The response contained all expected top-level keys:

```text
expected_regime
hypothesis
novelty_reason
proposal_id
research_run_id
strategy
```

The strategy object also contained every expected key:

```text
dsl_version
entry
exit
family
features
strategy_id
universe
vetoes
```

Therefore the prior `schema_rejected` result was value-level compatibility, not missing top-level fields. Raw values were not persisted or displayed.

## Implementation

Updated `creator_prompts.py` to derive and state the strict parser constraints:

```text
allowed strategy families
allowed feature names
positive lookback
shift >= 1
5m timeframe
15m regime context timeframe
```

Added a regression test proving these constraints remain present in the canonical prompt.

## TDD and verification

```text
prompt tests before change: 2 passed / 1 expected RED behavior
prompt tests after change:  3 passed
full suite:                671 passed
Ruff:                      passed
format:                    passed
mypy:                      passed
uv lock:                   passed
git diff --check:          passed
```

## Safety

```text
new candidate: 0
trial persistence: 0
OOS evaluation: 0
qualification: 0
orders: 0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
```

Next boundary: one real DeepSeek Creator smoke with the tightened prompt. Strict parsing remains fail-closed.
