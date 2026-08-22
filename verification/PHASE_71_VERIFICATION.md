# Phase 71 Verification — OpenCode-compatible Creator provider adapter

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 71 adds the direct OpenAI-compatible provider transport specified by the project proposal for the pinned embedded research model.

```text
explicit HTTPS base URL + in-memory API key
→ POST /chat/completions
→ exact deepseek-v4-flash-free model
→ strict JSON object extraction
→ existing Creator proposal Generator
```

## Delivered

New module:

```text
src/autonomous_futures/research/opencode_provider.py
```

New tests:

```text
tests/unit/test_opencode_provider.py
```

The adapter now:

- requires an explicit HTTPS base URL;
- requires an injected API key without persisting or logging it;
- pins `deepseek-v4-flash-free` with no fallback model;
- sends an OpenAI-compatible `/chat/completions` POST;
- parses only a JSON object from the assistant content;
- converts HTTP, transport, and malformed-payload failures to stable codes;
- never includes response bodies or authorization headers in error text;
- connects directly to the existing Creator Generator through `OpenCodeProposalTransport`.

## TDD evidence

```text
OpenCode adapter tests: 3 passed
All Creator tests:     21 passed
Full suite:            665 passed
Ruff:                  passed
format:                passed
mypy:                  passed
uv lock:               passed
git diff --check:       passed
```

Tests used `httpx.MockTransport`; no provider endpoint, API key, or network request was used.

## Explicit limitation

The adapter is implemented but not configured or deployed. OpenCode credentials remain absent from Kainode, and there is still no autonomous scheduler, research budget loop, critic/feedback loop, or automatic promotion. A real provider smoke requires explicit base URL and approved encrypted credential staging first.
