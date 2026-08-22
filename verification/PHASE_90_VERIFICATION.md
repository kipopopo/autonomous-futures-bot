# Phase 90 Verification — real Creator field-level schema diagnostics

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run exactly one real DeepSeek Creator request with safe schema diagnostics enabled.

```text
canonical prompt
→ OpenCode Zen
→ CreatorGenerator
→ generic schema_rejected + field/type diagnostics
```

No raw response values were printed, persisted, or included in the report.

## Actual result

```text
provider requests: 1
transport/authentication: successful
Creator decision: rejected
reason code: schema_rejected
candidate: absent
```

Safe diagnostics returned:

```text
proposal_id:string_pattern_mismatch
strategy.dsl_version:literal_error
strategy.entry:model_type
strategy.exit:model_type
strategy.universe.symbol:extra_forbidden
strategy.universe.symbols:missing
```

This identifies exact contract mismatches without exposing the model’s values. The failure is now actionable: the next prompt contract must require the exact proposal-ID pattern, integer DSL version, object-shaped entry/exit, and `universe.symbols` array rather than a singular `symbol` field.

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
project timers: 0
credential artifact: retained encrypted, root:root 600
```

## Conclusion

The real provider path is operational and the strict validator remains fail-closed. No candidate, trial, OOS, qualification, paper, or execution evidence exists from this run. Next implementation should update only the prompt’s exact field-shape instructions and tests, then run another bounded smoke.
