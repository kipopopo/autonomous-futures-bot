# Phase 237 Verification — Bounded Critic-Guided Revision

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **CLOSED / REVISION-REJECTED / SAME-FAMILY-STOP**

## Scope

Consume the verified Phase 236 rejection through the existing Learner/Critic and Creator revision contracts, issue one bounded Critic request and one bounded Creator request, evaluate the revision against the same immutable cached OOS data and unchanged qualification policy, and stop on deterministic failure.

Runtime:

```text
model=gpt-5.6-sol
provider=openai-codex
effort=Medium
```

Remote provider:

```text
provider=google_ai_studio
model_id=gemma-4-31b-it
```

No production code change was required. Existing typed readers, failure-feedback projection, Critic review/evidence persistence, revision prompt, canonical candidate identity, cached evaluator, walk-forward aggregation, and strict qualification were reused.

## Local contract preflight

```text
focused tests=31 passed
source_commit=84d32f37b875e6c5f4c46ecc78d20853112174ee
source_archive_sha256=f19baffe70b3e8648dfaa353174ca6e5212e395574c357375a6f86b6d005a7b2
provider_source_sha256=a8cde3b33d401a00cdfcfa0653733f6f6e859be64a96682a5da9714c5fcc36cb
```

## Source rejection

```text
candidate_id=cand-b7e9c6760fca8fcd07ad2174901eeae63a5b7b844b73c22950d258e9a983ecaa
candidate_artifact_hash=b9b17c5c62e846e52266824f8467a2b247a6d2c0c6e8005529a3a5412aceebbc
qualification_hash=ae35ac21f2c13a304f1d7623c42b81cfa563f7c53291b527891b347e6b9700b2
source_decision=rejected
source_profit_factor=0.4689108485659958856205209325
source_average_return_pct=-31.05559886372132246484035105
source_worst_drawdown_pct=35.70874934456935594134251960
```

## Permission preflight repair

The first Critic unit (`critic-campaign-20260902-005`) could not read the root-owned Phase 236 evidence:

```text
failure_type=PermissionError
provider_requests=0
critic_evidence=false
blocked_summary_sha256=162c43a0feb599be9246ea38a0f36928e871fcf8d7886c80f85233d0cc18541e
```

No provider budget was consumed. The protected immutable root was not relaxed. The exact verified candidate and qualification files were copied to a private temporary input root for the unprivileged one-shot unit. The blocked record remains immutable evidence.

## Critic request

```text
campaign_id=critic-campaign-20260902-006
runner_sha256=f472f510351c85d011bc2067f0d0b1c19a0cc91206a7ddda7c9b3c831c9f7a74
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
content_length=691
content_sha256=4c499eb193f1b2b6e62438f0d5f7b050c07c07bd8caa9d0259563a2a2a3c7c65
result_decision=accepted
critique_decision=revise
review_hash=8c1ee86efacb8266953f445675aecabd596953c03700b4d3ff642873d703ef27
evidence_hash=2cbb5ddd3fc392ed45626fab30670edff5bb955e2b66b1d73baadf214844689a
```

Persisted evidence file SHA-256 values:

```text
critic-evidence.json=67852e099df6fa9933795f9cb6752615e9932d04f806495b14ce69193817011d
critic-summary.json=35751433c89c1e5e137ce21f4b8699c0599db78ed7948eda845f60728e43389d
```

Critic actions:

```text
adjust_atr_stop_multiplier
adjust_target_multiplier
optimize_position_fraction
optimize_trailing_multiplier
```

All four actions were checked before the Creator request and found representable by the existing typed risk/evaluator contract. Unsupported leverage, qualification, promotion, paper, and order actions remained forbidden.

## Creator revision request

```text
campaign_id=creator-batch-20260902-007
runner_sha256=35fc2ac5f2934c6885be9b65949aac6eb93b6b712dcb633edf2d6f90a78d1eae
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
content_length=1750
content_sha256=e45961ca368fb9191904780ad43f5984be913f51acb30d43c57676720a5ecb36
generation_decision=accepted
generation_reason=schema_valid
```

The request was bound to the source candidate, source qualification, persisted Critic evidence, immutable bundle, dataset registry, and complete runtime lineage snapshot:

```text
forbidden_candidate_count=51
forbidden_candidate_snapshot_sha256=7a23596e983398ae694c0f5e3d8a4f6e49aec99e2b933a2aadc23a19efa9e773
```

## Revised candidate

```text
candidate_id=cand-e3dd9d596914084d90ff86ed8af3d5ec40c9bdc7ed4d9535b077230642aacbe9
candidate_artifact_hash=0fc119b3839684f4ebf5091b361171c5bdbd3cc378bc411eac533ee3e2323a1e
candidate_registry_hash=34d3f5a6782fc655559deedf4fe375a5b4e516e311b0f9a63d45969ed8bbb10c
state=testing
family=regime_gated_breakout
position_fraction=0.1
stop_atr_multiplier=2.5
take_profit_atr_multiplier=4.0
trailing_atr_multiplier=1.5
```

The canonical candidate ID differs from the source candidate and was not in the forbidden snapshot.

## Cached OOS result

```text
windows=4
trades=16581
pooled_profit_factor=0.4407645772120027858094119184
average_return_pct=-40.0286438208788205706174186
worst_drawdown_pct=44.22577089233561883461020487
aggregation_hash=82d6bc7a9404c7b2e1336219034f16132e44cbbe7aaecfcbcda69d59d7a56f22
```

The revised same-family strategy was worse than its parent on profit factor, average return, and drawdown.

## Qualification

```text
decision=rejected
qualification_hash=59957a81f26eba93f36639d3ed7357ac26126496bdd7842e66901d8e7aeb6772
failed_gates:
- oos_average_return_below_threshold
- oos_drawdown_above_threshold
- oos_profit_factor_below_threshold
- oos_symbol_average_return_below_threshold
- oos_symbol_drawdown_above_threshold
- oos_symbol_profit_factor_below_threshold
```

No gate was relaxed and no negative evidence was overridden.

## Immutable Creator evidence

```text
file_count=6
evidence_snapshot_sha256=6065c4b7335fa2951923f02de615eb9fc07f0ba54c80e3d00b83dcbb77756a0a
campaign-summary.json=4a81364dd33cad6b8936eb28611bf0e9ced4d40758773e9335558cce1157c3f6
candidate-registry.json=8c4a6a3255fbc65abc1cacf178c733a555d3902aaa0bca73a2ba43afa72c1409
candidate=5b0fe695dd1a84e7c3ece7eb3d1ef0ff0c6ddbcab13285cad4fd33d2f72ec7d0
oos=2e1f3f18ea63c583dac4d457bd97273823d2815da49aea3a82fc775ea6a5a222
qualification=7e94e46a3b74f14532b39a9c337ee364855b8cad954a22c47243d48d75f19f3f
trial=b6964344eaa3f4e9ab9edccb54a7c96e2885b98b10afe7eab22d31b9aa0e4694
```

Every Critic, candidate, registry, trial, OOS, and qualification artifact was read through its shared hash-verifying reader before cleanup.

## Safety and cleanup

```text
total_provider_requests=2
critic_requests=1
creator_requests=1
automatic_retry=false
fallback_provider=false
raw_prompt_persisted=false
raw_provider_response_persisted=false
credential_persisted=false
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
matching_python_processes=0
critic_unit=not-found
creator_unit=not-found
research_timers=0
remote_transients=absent
local_transients=absent
```

## Stop condition

This bounded same-family revision loop is closed. The Critic-guided revision repeated the `regime_gated_breakout` family under unchanged gates and produced materially worse deterministic OOS evidence. No further blind seed, retry, Critic follow-up, gate relaxation, promotion, or activation is justified.

Any next research campaign must open a materially new falsifiable boundary, such as a different supported strategy family or new immutable evidence scope, and requires separate approval before another provider request.
