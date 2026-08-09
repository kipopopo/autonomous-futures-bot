# Phase 3AF Verification — Provider-Agnostic LLM Research Policy and Audit Contracts

## Status

**GREEN — Phase 3AF scope verified locally.**

Phase 3AF establishes the first pure-domain boundary for the Autonomous LLM Research Lab:

```text
explicit embedded research-role policy
→ exact provider/model pinning
→ deterministic canonical policy hash
→ in-memory, hash-bound model-call audit
```

It is a contract-only slice. It does not contact an LLM provider, retain provider credentials, render prompts, persist audits, parse a StrategySpec, create a candidate, execute generated code, schedule work, qualify/promote a candidate, activate paper observation, access an exchange, route an order, or grant execution authority.

## Model-tier decision

Development runtime:

```text
model:    gpt-5.6-terra
provider: openai-codex
effort:   Medium
```

`terra + Medium` was sufficient because this phase is bounded pure-domain integration using existing Pydantic and canonical-hash patterns. No silent model or effort change occurred.

The embedded application policy is deliberately separate from development routing:

```text
provider: opencode
model:    deepseek-v4-flash-free
```

This derives from the accepted proposal and is a typed, exact pin—not a provider call or deployment-ready credential configuration.

## Delivered contract

### Research role policy

New module:

```text
src/autonomous_futures/research_lab/model_policy.py
```

It provides:

```text
LLMRolePolicy
ResearchModelPolicy
build_research_model_policy(...)
research_model_policy_content_hash(...)
```

Policy fields are explicit:

```text
role
provider
model_id
temperature
max_output_tokens
max_requests_per_batch
max_retries
policy version/id
canonical policy hash
```

The policy enforces:

```text
provider == "opencode"
model_id == "deepseek-v4-flash-free"
0 <= temperature <= 2 and finite
max_output_tokens > 0
max_requests_per_batch > 0
max_retries >= 0
roles sorted and unique
caller-supplied policy-hash drift rejected
```

There is no fallback provider/model field and no model self-selection capability.

### Model-call audit

New module:

```text
src/autonomous_futures/research_lab/model_audit.py
```

It provides an in-memory `ModelCallAudit` record with:

```text
research run/call identity
role and exact policy id/hash binding
provider/model pin
prompt-template hash and system-policy version
sorted unique input-evidence references
output-schema identity/outcome
output hash only; never raw output
optional token metadata, price tier, rate-limit delay, retry count, error code
UTC observed_at
canonical audit hash
```

Supported outcomes are:

```text
succeeded
schema_rejected
provider_model_unavailable
provider_error
budget_rejected
```

Fail-closed outcome rules:

```text
succeeded                  -> output_hash required; error_code forbidden
unsuccessful outcome       -> output_hash forbidden; error_code required
budget_rejected            -> input/output token usage forbidden
provider_model_unavailable -> input/output token usage forbidden
non-UTC observed_at        -> rejected
audit-hash drift           -> rejected
```

`observed_at` is explicitly excluded from `audit_hash` content calculation, together with `audit_hash` itself. Rebuilding otherwise identical audit content at a different UTC observation time therefore retains the same content hash. A future immutable persistence boundary must still reject a write-once path collision when the typed audit timestamp differs.

## TDD evidence

### RED → GREEN sequence

1. `test_research_lab_model_policy_is_pinned_sorted_and_canonically_hashed` failed with `ModuleNotFoundError` before the policy module existed, then passed after minimal package/policy implementation.
2. Budget/drift policy tests initially produced six failures for missing bounds, duplicate-role, and supplied-hash checks, then passed after validation was added.
3. The model-call audit success test failed with `ModuleNotFoundError` before the audit module existed, then passed after the pure audit envelope was added.
4. Audit outcome/UTC/hash tests initially produced six missing-invariant failures, then passed after semantic validation was added.
5. Two final guard tests initially failed for unavailable-token metadata and unordered input evidence references, then passed after narrow validation additions.

Focused result:

```text
18 passed in 0.33s
```

New tests:

```text
tests/unit/test_research_lab_model_policy.py
tests/unit/test_research_lab_model_audit.py
```

## Full verification

| Check | Actual result |
|---|---|
| Locked backend suite | `298 passed in 11.70s` |
| Ruff lint | `All checks passed!` |
| Ruff format | `108 files already formatted` |
| mypy | `Success: no issues found in 64 source files` |
| Lock check | passed (`Resolved 67 packages in 1ms`) |
| `compileall` | passed |
| `git diff --check` | passed |
| Frontend Vitest | `39 passed` |
| Frontend TypeScript build | passed |
| Frontend lint | `0 warnings / 0 errors` |
| Frontend production build | passed |

## Safety scan

The new `research_lab` Python package was scanned for:

```text
httpx | requests | websocket | binance | exchange | order | execution |
write_ | os. | subprocess | eval( | exec( | importlib |
credential | secret | api_key | qualification | promotion |
paper_activation | creator
```

Result:

```text
__init__.py:    no matches
model_audit.py: no matches
model_policy.py: lexical "requests" and "order" only
```

Manual follow-up classified the two policy-module lexical hits:

```text
max_requests_per_batch -> typed quota field; not an HTTP/provider request
ordered collection     -> deterministic tuple ordering; not a trading order
```

No restricted capability, dependency, import, write path, exchange path, order path, dynamic execution path, credential field, candidate/qualification/promotion import, or paper/execution authority is present in the delivered package.

## Deferred scope

The following need distinct future contracts and are not implied by Phase 3AF:

```text
OpenCode base URL/credential delivery
provider model-catalog preflight
OpenAI-compatible HTTP client
prompt-template/evidence-bundle rendering
raw output handling and schema-to-StrategySpec parsing
immutable audit persistence
research batch budgets and bounded concurrency scheduler
trial/candidate persistence and deterministic evaluation
candidate qualification, promotion, paper activation, and execution
API or dashboard exposure
```

Phase 3AF does not make any model provider reachable, any autonomous research cycle runnable, or any trading environment authorized.
