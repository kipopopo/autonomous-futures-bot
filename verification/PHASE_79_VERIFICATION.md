# Phase 79 Verification — switch OpenCode research model to DeepSeek V4 Flash

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Decision

The project now uses the paid OpenCode Zen DeepSeek V4 Flash model, replacing the ephemeral Ox Alpha Free model.

```text
provider: OpenCode
model: deepseek-v4-flash
endpoint: https://opencode.ai/zen/v1/chat/completions
fallback: none
```

Updated active source contracts:

```text
src/autonomous_futures/research_lab/model_policy.py
src/autonomous_futures/research_lab/model_audit.py
src/autonomous_futures/research/opencode_provider.py
```

Updated all active policy/audit/provider tests and current proposal/pre-development/credential documentation. Historical phase reports remain immutable.

## Safety

```text
provider fallback: none
new provider requests after switch: 0
exchange access: false
paper activation: false
execution authority: false
orders: 0
```

Encrypted OpenCode credential remains root-owned mode `600`; its value was not printed, persisted in Git, or placed in reports.

## Verification

```text
full suite: 666 passed
Ruff: passed
format: passed
mypy: passed
uv lock: passed
git diff --check: passed
```

A new real DeepSeek V4 Flash smoke is a separate paid provider-request boundary.
