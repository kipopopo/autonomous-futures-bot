# Phase 75 Verification — switch OpenCode research model to Ox Alpha Free

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Decision

The embedded OpenCode research model is changed from the previously pinned DeepSeek free model to the user-selected Ox Alpha Free model.

```text
provider: OpenCode
model name: Ox Alpha Free
model ID: x-preview-f-free
endpoint family: OpenAI-compatible /v1/chat/completions
fallback: none
```

The model ID was recorded as `x-preview-f-free` from the current OpenCode model discovery evidence. The application remains fail-closed if that model is unavailable.

## Updated active contracts

```text
src/autonomous_futures/research_lab/model_policy.py
src/autonomous_futures/research_lab/model_audit.py
src/autonomous_futures/research/opencode_provider.py
```

Updated policy/audit/provider tests and current proposal, pre-development, and credential-handling documentation. Historical phase reports retain their original model identity and are not rewritten.

## Safety

```text
provider fallback: none
exchange access: false
paper activation: false
execution authority: false
order capability: false
new provider request after model switch: 0
```

The encrypted OpenCode credential remains staged at Kainode with root-only mode `600`; no credential value was printed or committed.

## Verification

```text
full suite: 665 passed
Ruff: passed
format: passed
mypy: passed
uv lock: passed
git diff --check: passed
```

A real smoke with `x-preview-f-free` remains a separate provider request boundary. The previous smoke blocker was recorded before this model switch.
