# Phase 65 Verification — injected Creator Generator boundary

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 65 adds the provider-agnostic Creator Generator seam over the Phase64 proposal boundary.

```text
CreatorGenerationRequest
→ injected ProposalTransport
→ strict CreatorProposal parser
→ accepted proposal or stable rejection result
```

## Delivered

New module:

```text
src/autonomous_futures/research/creator_generator.py
```

New tests:

```text
tests/unit/test_creator_generator.py
```

The Generator now:

- accepts only evidence references and a research-run identity in its request;
- calls an injected transport, so tests do not need a provider/network;
- validates the returned payload through the strict Creator proposal boundary;
- rejects schema-invalid payloads with `schema_rejected`;
- rejects research-run provenance drift with `research_run_mismatch`;
- converts transport failures to stable `provider_error` without exposing exception text;
- never returns or persists raw provider output;
- preserves `unpromoted`, paper-disabled, execution-disabled, and exchange-disabled safety fields.

## TDD evidence

```text
initial RED: missing creator_generator module
Creator proposal tests: 3 passed
Generator tests:        4 passed
full suite:             651 passed
Ruff:                   passed
format:                 passed
mypy:                   passed
uv lock:                passed
git diff --check:       passed
```

## Explicit limitation

This is an injected Generator seam, not a live provider adapter. No OpenCode request was made. The repository still needs a separately configured OpenCode-compatible base URL/credential contract before direct provider access can be added. There is still no autonomous scheduler or Creator feedback loop.

The next safe slice is a fake-client-backed Creator batch runner that validates multiple proposals, records accepted/rejected outcomes, deduplicates candidate identity, and never promotes. Provider wiring remains separate.
