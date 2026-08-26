# Phase 173 Verification — complete historical proposal guard

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

The first bounded request returned `cand-doge-regime-breakout-005`, which had already appeared as an earlier accepted-but-unpersisted proposal in the historical verification reports. It was discarded before candidate persistence or OOS. The corrected request used the union of:

```text
verified persisted registry/artifact candidate IDs
+ candidate IDs recorded in historical verification reports
```

This closed the gap between persisted registry history and previously observed proposal history without changing production gates.

## Corrected actual result

```text
source candidate:        cand-doge-meanrev-007
critic evidence:         critic-evidence-021
historical forbidden IDs:22
corrected provider calls:1
Creator decision:        accepted
proposal:                proposal-doge-trend-filter-001
candidate:               cand-doge-trend-filter-001
candidate_is_forbidden:  false
reason:                  schema_valid
```

The corrected proposal was not persisted or evaluated in this slice.

## Safety and cleanup

```text
candidate persistence: 0
OOS:                   0
qualification:         0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
temporary units/source: removed
local temporary files: deleted
project timers=0
```

## Verification

```text
full suite before smoke: 698 passed
Creator/prompt tests:    18 passed
Ruff/format/mypy/lock:   passed
remote source parity:    passed
remote cleanup:          passed
```

## Conclusion

The complete historical candidate/proposal guard rejected a repeated unpersisted proposal and accepted a new schema-valid candidate identity. Stop before persistence/OOS at this corrected proposal boundary.
