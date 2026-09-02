# Phase 236 Verification — Canonical Creator Campaign

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **GREEN / CAMPAIGN-COMPLETED / QUALIFICATION-REJECTED**

## Scope

Run exactly one bounded Creator campaign from pushed source after closing the historical canonical-lineage prerequisite.

Runtime selected by the user:

```text
model=gpt-5.6-sol
provider=openai-codex
effort=Medium
```

Remote Creator provider:

```text
provider=google_ai_studio
model_id=gemma-4-31b-it
```

## Canonical lineage prerequisite

Historical artifacts retain their original provider-authored IDs. Before any provider request, the existing canonical identity function was exposed so a historical `StrategySpec` can be mapped to the same trusted local identity used for new proposals.

Strict TDD evidence:

```text
RED: ImportError: cannot import name 'canonical_creator_candidate_id'
GREEN focused: 11 passed
full: 716 passed
```

Prerequisite source commit:

```text
b7178f5b3f980698ccc825f17e16caf78416c75f
```

The complete campaign snapshot included both original historical IDs and canonical IDs derived from persisted strategies:

```text
historical_candidate_count=50
historical_candidate_snapshot_sha256=6186271ed85efa136d4a4b46501fd1e06c20d6768de803a27e1571767f707ba1
```

Invalid historical strategy content fails the preflight rather than being silently skipped.

## Exact-source binding

```text
source_commit=b7178f5b3f980698ccc825f17e16caf78416c75f
runner_sha256=5f5cf044af128961e64eb621f8fbe58d2dc1d331530b02efc2a555f357ead331
archive_sha256=a5c44adc7c73c74cec9876032b5d9d4c362c3097ede915a9d3c2c07fa33e6d3d
provider_source_sha256=a8cde3b33d401a00cdfcfa0653733f6f6e859be64a96682a5da9714c5fcc36cb
```

Pinned SSH used the trusted out-of-band Ed25519 fingerprint. Host-key checking was not bypassed.

## Cached-data preflight

```text
catalog_components=5
artifact_inspections=5
primary_rows=105120
bundle_hash=19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816
dataset_registry_hash=583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb
data_source=cached_only
exchange_access=false
```

## Provider attempt

```text
campaign_id=creator-batch-20260902-004
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
thinking_level=minimal
include_thoughts=false
response_format=json_object
content_length=1597
content_sha256=aad86a4092487594e114dc906b32cdf0107b6aae1a7d82d681091218535ddd97
generation_decision=accepted
generation_reason=schema_valid
```

Raw prompt and raw provider response were not persisted.

## Deterministic evaluation

The trusted local boundary assigned:

```text
candidate_id=cand-b7e9c6760fca8fcd07ad2174901eeae63a5b7b844b73c22950d258e9a983ecaa
candidate_artifact_hash=b9b17c5c62e846e52266824f8467a2b247a6d2c0c6e8005529a3a5412aceebbc
candidate_registry_hash=72a7addf1679ecd1a95daaa6d4c2607aeacbcc691f5a4cb2e92f3c56edb7c332
state=testing
```

Cached OOS result:

```text
windows=4
trades=5774
pooled_profit_factor=0.4689108485659958856205209325
mean_window_return_pct=-31.05559886372132246484035105
worst_drawdown_pct=35.70874934456935594134251960
aggregation_hash=48a82003a9d4a32400a8b1fc986043693140f27e33a3572ee1cc90c9b1a35163
```

## Qualification

```text
decision=rejected
qualification_hash=ae35ac21f2c13a304f1d7623c42b81cfa563f7c53291b527891b347e6b9700b2
failed_gates:
- oos_average_return_below_threshold
- oos_drawdown_above_threshold
- oos_profit_factor_below_threshold
- oos_symbol_average_return_below_threshold
- oos_symbol_drawdown_above_threshold
- oos_symbol_profit_factor_below_threshold
```

Negative OOS evidence is final for this candidate. It was not qualified, promoted, or activated.

## Immutable readback

Every trial, candidate, registry, aggregation, and qualification artifact was read independently through its typed hash-verifying reader.

```text
final_root=/var/lib/autonomous-futures/research/dogeusdt-365d-typed-20260902-001/creator-batch-20260902-004
file_count=6
evidence_snapshot_sha256=3806ceca6329cacf3b4cb5e76ff527e13b95ac0184d1fd56274b550735edf5e3
```

Persisted file SHA-256 values:

```text
campaign-summary.json
9da67c2f80c6e97f08520739d60b7505c6a7a6475d80a64fd18012acb8f0deb7
candidate-registry.json
b63dc675a70db2cbee713e980c6994f3c2da4de3cf3025561d7b1b072b0688d4
candidate artifact
660377afafb76c599c71a8b0034323197fe7a08e8dbbdafd16982a8852c0e90e
OOS aggregation
7b30126411a7a836136731ba762109ec50c0a9853de4840d44ce912545f60a2d
qualification
369491b37557351bc550e745a464ed9e03cdef5446a6fdca947c3c59fa0b0be7
trial
c4dfe986e7a3e2dacb5796b2af92ef3943ee6fe8e21d9b84344702aa31e0612e
```

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
automatic_retry=false
fallback_provider=false
raw_prompt_persisted=false
raw_provider_response_persisted=false
credential_persisted=false
matching_processes=0
unit_load_state=not-found
research_timers=0
remote_transients=absent
local_transients=absent
```

## Boundary

Do not retry this candidate or relax qualification gates. The next materially different research boundary is to consume this persisted qualification failure as bounded Creator/Critic revision evidence; that requires a separate provider request and must retain the same cached-only, one-request, no-retry, no-fallback safety envelope.
