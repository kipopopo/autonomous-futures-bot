# Autonomous Research Base v1 — Verification

**Date:** 2026-09-13
**Scope:** offline autonomous research/learning orchestration only
**Safety state:** cached-only, unpromoted, paper-disabled, execution-disabled

## Delivered

Base v1 composes the existing bounded deterministic research cycle with two typed embedded-AI seams:

```text
complete rejected-history memory
→ failure learner
→ falsifiable research planner
→ bounded Creator/Critic/OOS/WF cycle
→ immutable cycle checkpoint
→ next failure-memory entry
→ next materially-different experiment
```

Implemented contracts and behavior:

- `FailureMemoryEntry` — hash-bound rejected-gate history with candidate, qualification, scope, and failed-gate lineage.
- `FailureLearningRequest` / `FailureLearningArtifact` — complete-history failure analysis with explicit constraints and novelty dimensions.
- `ResearchPlanRequest` / `ResearchPlan` — one falsifiable plan tied to the full failure memory, learner output, fixed dataset scope, and complete forbidden candidate set.
- Stable `thesis_hash` — rejects the same thesis even when the cycle ID or full plan hash changes.
- `AutonomousResearchBase` — finite `max_cycles` loop with immutable seed, learning, plan, cycle, failure-memory, and final-result artifacts.
- Existing-cycle adapter — invokes the existing deterministic cycle with `paper_engine=None` and forwards the approved plan to Creator.
- Creator prompt binding — includes plan hypothesis, expected regime, family, novelty dimensions, falsification criteria, and plan hash.
- Canonical learner/planner prompts — authority-denying, evidence-only prompts; raw provider output is not retained.
- Direct Google AI Studio learner/planner transports — compose the canonical prompts with the existing JSON client and preserve only allowlisted metadata; no retry/fallback policy is added.
- Policy-bound learner/planner transports — bind each call to the pinned research role/model policy and emit only hash-bound, non-authoritative `ModelCallAudit` records through an injected sink; credentials and raw provider content remain outside the audit.
- Typed provider factory — wires separate role-specific clients into `AutonomousResearchBase`; construction validates policy/model bindings and cannot bypass the audit sink or invoke HTTP.
- Prepare-only provider smoke contract/CLI — creates a single-request, role-bound artifact with `network_call_allowed=false`; it accepts only a sanitized policy file and has no credential resolver or HTTP path.
- Safe schema diagnostics — learner/planner intake now reports only allowlisted field paths and typed validation codes; unknown provider fields and values are omitted.
- Write-once, hash-verified persistence and final-result idempotency/resume behavior.

## Safety invariants

The Base v1 boundary rejects or preserves:

- `data_source="cached_only"`
- `promotion_state="unpromoted"`
- `paper_activation=false`
- `execution_authority=false`
- `exchange_access=false`
- admitted cycle output
- duplicate historical candidate IDs
- replayed thesis fingerprints
- incomplete failure-memory scope
- rejected qualification without typed next feedback
- non-UTC timestamps and tampered hashes

The Base API has no paper engine, order router, breaker control, risk mutation, leverage authority, testnet path, or live path.

## Changed files

- `src/autonomous_futures/research/autonomy_contracts.py`
- `src/autonomous_futures/research/autonomy_prompts.py`
- `src/autonomous_futures/research/creator_generator.py`
- `src/autonomous_futures/research/creator_prompts.py`
- `src/autonomous_futures/research/autonomy_provider.py`
- `src/autonomous_futures/research/provider_smoke.py`
- `src/autonomous_futures/research/__init__.py`
- `src/autonomous_futures/pipeline/autonomous_base.py`
- `src/autonomous_futures/pipeline/autonomous_cycle.py`
- `src/autonomous_futures/pipeline/__init__.py`
- `tests/unit/test_autonomous_research_base.py`
- `tests/unit/test_autonomy_provider.py`
- `tests/unit/test_autonomy_provider_audit.py`
- `tests/unit/test_autonomy_provider_wiring.py`
- `tests/unit/test_provider_smoke.py`
- `tests/unit/test_autonomy_schema_diagnostics.py`
- `scripts/prepare_autonomy_provider_smoke.py`

## Verification

- Base/Creator/Critic/cycle/provider/audit/wiring/smoke-preparation/schema-diagnostics/prompt focused suite after the remediation: **54 passed in 1.49s**.
- Targeted Ruff: **pass**.
- Targeted Ruff format: **pass**.
- Targeted mypy: **pass**.
- Full locked pytest after the final orphan-resume correction: **2,247 passed in 886.62s**.
- No provider calls beyond the two separately authorized single-request smokes, exchange access, paper activation, candidate admission, restart, order, testnet action, or live action were performed.

## Authenticated smoke gate

An explicit authorization was received for exactly one bounded `failure_analyst`
request. The request was built from the verified rejected VWAP evidence and the
prepare-only safety contract was checked before credential resolution. The
supported credential resolved without exposing its value, and exactly one
Google AI Studio request was sent with the pinned `gemma-4-31b-it` model.

```text
credential source:       supported environment/repository resolver only
resolver result:         resolved (value not retained or displayed)
provider requests:       1
network call:            true, exactly one authorized request
provider HTTP status:    200
transport outcome:       succeeded
learner decision:        rejected / schema_rejected
schema diagnostic:       learning_payload_invalid
response content length: 1408
response content hash:   e8278b18d748d7860b6210d1ec617b53d9ade7fa420d462f2aa63de067f17eba
finish reason:           stop
audit hash:              4d624f13b190d5bc294dca0881cd8270361d64cee0e45c4f5c28f09219f355d2
audit envelope hash:     eae02d37ef2f0ae74cdb20e39b83125a30a769b309939a79eb1d1bf456716d90
raw provider output:     not persisted
raw credential persisted: false
```

The audit envelope was written to a temporary path, read back with the shared
hash-verifying reader, and removed with the disposable runner. No credential
was requested in chat, printed, logged, or substituted from another provider.
No retry, fallback, learner-artifact persistence, planner call, research cycle,
or execution path was started after the schema rejection.

## Schema diagnostic follow-up

A separate explicit authorization was received for one diagnostic
`failure_analyst` request. It used the same verified VWAP evidence and the
remediated safe-diagnostic intake; exactly one request reached the provider.

```text
research run:            run-provider-schema-diagnostic-001
provider requests:       1
provider HTTP status:    200
transport outcome:       succeeded
learner decision:        rejected / schema_rejected
response content length: 1313
response content hash:   41a4b608ab35a1c44f1aa0048da806522449bb4f3eef605ec8cd89e759c642aa
safe schema diagnostics: failure_patterns.0:string_type
                          failure_patterns:too_short
                          learned_constraints.0:string_type
                          learned_constraints:too_short
                          recommended_novelty_dimensions.0:literal_error
                          recommended_novelty_dimensions.1:literal_error
                          recommended_novelty_dimensions.2:literal_error
                          recommended_novelty_dimensions:too_short
audit hash:              abfc544864fafbc2e87a27c4d5e642a1a750e806a4a93a3434c6723b3c1ee873
audit envelope hash:     d874a060d64d8dbb79558ec034a6bd09793d361614a1863dea32ec90a40e9cce
raw provider output:     not persisted
```

The diagnostic result identifies a provider response-shape mismatch: the
learner arrays were not accepted as the required string arrays and the novelty
values were outside the typed enum. The canonical prompt now states those
requirements explicitly. No schema relaxation or third request was performed.

## Honest limitations / next boundary

- The failure learner is an explicit typed failure-analysis seam; this slice does not silently invent a new ML trainer or claim model-quality improvement.
- The two real provider smokes reached the provider successfully but failed at the typed learner-schema boundary. The second run captured safe field/type diagnostics, while both raw responses remain intentionally unrecovered; no blind retry or schema relaxation is authorized.
- The smoke-preparation artifact is deliberately non-authorizing (`network_call_allowed=false`); it cannot be used as proof of provider availability or entitlement.
- Existing learner model training/evaluation artifacts remain separate and require an explicit objective, causal inputs, trainer, and their own evidence boundary.
- Current paper runtime remains `HALTED`; this work does not create resume authority or change the deployed runtime.
- Qualification, paper admission, testnet, and live promotion remain separate decisions.
