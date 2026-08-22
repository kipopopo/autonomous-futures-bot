# Phase 86 Verification — canonical Creator prompt smoke

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run exactly one real Creator request using the canonical prompt builder introduced in Phase 84 and the stable provider error propagation fixed in Phase 85.

```text
canonical prompt
→ OpenCode Zen
→ deepseek-v4-flash
→ OpenCodeProposalTransport
→ CreatorGenerator
```

No candidate, trial, cached OOS, qualification, paper, or order path was invoked.

## Actual result

```text
provider requests: 1
transport/authentication: successful
Creator decision: rejected
reason code: schema_rejected
proposal_id: absent
candidate_id: absent
```

The provider response reached the existing strict proposal parser but did not satisfy `creator-proposal-v1`. The Generator rejected it without exposing or persisting raw model output. The preserved provider error-code path remains available for transport/payload failures; this run reached schema validation instead.

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

The real provider path and canonical prompt are operational, but DeepSeek’s returned proposal is still incompatible with the strict Creator schema. No candidate or OOS evidence may be claimed from this run. Next work should use safe response metadata or a narrower provider-compatible proposal contract; it must not weaken StrategySpec validation or accept arbitrary prose.
