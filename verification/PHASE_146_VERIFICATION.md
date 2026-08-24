# Phase 146 Verification — complete Creator lineage guard

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Fix the second lineage bug found during Critic-guided revision:

```text
immediate parent forbidden
→ older historical candidate repeated
```

The revision request now requires a complete forbidden candidate-ID snapshot, and the prompt includes that snapshot. The shared Generator rejects any returned candidate in the set before persistence.

## Actual result

One corrected real Critic-guided Creator request with all six historical candidate IDs forbidden:

```text
forbidden prior IDs:     6
source candidate:        cand-doge-breakout-001
provider requests:       1
Creator decision:        accepted
proposal:                proposal-doge-meanrev-003
candidate:               cand-doge-meanrev-003
candidate_is_forbidden:  false
reason:                  schema_valid
```

## Safety

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
project timers: 0
```

## Verification

```text
Creator/prompt tests:    18 passed
full suite before smoke: 698 passed
Ruff/format/mypy/lock:   passed
remote source parity:    passed
remote cleanup:          passed
```

An earlier attempt exposed the duplicate historical candidate and was not treated as a valid revision. The corrected run used the full prior-ID set and passed the guard.

## Conclusion

Critic-guided Creator lineage now rejects both immediate-parent repetition and known historical candidate repetition when the caller supplies the complete registry snapshot. Stop before persistence/OOS at this corrected major boundary.
