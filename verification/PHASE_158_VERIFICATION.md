# Phase 158 Verification — Creator feature-object schema alignment

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Diagnose and fix the real Creator schema mismatch:

```text
provider output: features[].feature_name
strict schema:   features[].name/lookback/shift
```

The Creator prompt now explicitly requires:

```text
feature objects must use keys name, lookback, and shift
```

No schema weakening or provider-value coercion was added.

## Actual real-smoke result

Using `critic-evidence-016` with ten forbidden historical candidate IDs:

```text
provider requests:      1
Creator decision:       accepted
proposal:               proposal-doge-meanrev-006
candidate:              cand-doge-meanrev-006
candidate_is_forbidden: false
reason:                 schema_valid
```

The candidate was not persisted or evaluated in this slice.

## Safety and cleanup

```text
candidate persistence: 0
OOS:                   0
qualification:         0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
temporary systemd unit: removed
local temporary files: deleted
project timers=0
```

## Verification

```text
Creator/prompt tests:    18 passed
full suite before smoke: 698 passed
Ruff/format/mypy/lock:   passed
remote source parity:    passed
remote cleanup:          passed
```

## Conclusion

The real Creator provider now satisfies the strict feature-object field contract on this bounded request. Stop before candidate persistence/OOS at this corrected proposal boundary.
