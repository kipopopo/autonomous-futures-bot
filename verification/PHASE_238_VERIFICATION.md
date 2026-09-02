# Phase 238 Verification — Range Mean-Reversion Family Campaign

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **COMPLETED / NEW-FAMILY / QUALIFICATION-REJECTED**

## Scope

Open one materially different falsifiable strategy-family boundary after closing the failed `regime_gated_breakout` loop. Run exactly one Creator request pinned to `range_mean_reversion` with a required causal `bollinger_zscore` feature, then apply the existing immutable persistence, cached OOS, and unchanged strict qualification chain.

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

No production code or dependency change was required. The campaign reused the existing prompt, strict proposal parser, trusted canonical candidate identity, cached evaluator, walk-forward aggregation, qualification, and immutable readers/writers.

## Exact-source and local preflight

```text
source_commit=1e50c7bc57ccdd5474b7d771d41bb6f66c9ccd57
runner_sha256=e5fd07615c952853291e06f6df0226ad635c69a8a876e23324f406c88a2430a7
source_archive_sha256=be6efc286dcce79f8f78f432914ef05034a5a45f11a46ef4f051e5ed52958462
provider_source_sha256=a8cde3b33d401a00cdfcfa0653733f6f6e859be64a96682a5da9714c5fcc36cb
focused_tests=31 passed
family_contract_selfcheck=PASS
```

The operational family guard required both:

```text
strategy.family=range_mean_reversion
required_feature=bollinger_zscore
```

A schema-valid proposal using `regime_gated_breakout`, `experimental`, or omitting `bollinger_zscore` would have been rejected before candidate persistence.

## Prior rejected evidence binding

The request was bound to the two verified rejected trend-family candidates:

```text
candidate_004=cand-b7e9c6760fca8fcd07ad2174901eeae63a5b7b844b73c22950d258e9a983ecaa
qualification_004=ae35ac21f2c13a304f1d7623c42b81cfa563f7c53291b527891b347e6b9700b2
candidate_007=cand-e3dd9d596914084d90ff86ed8af3d5ec40c9bdc7ed4d9535b077230642aacbe9
qualification_007=59957a81f26eba93f36639d3ed7357ac26126496bdd7842e66901d8e7aeb6772
```

Protected source evidence remained root-owned. Only the four exact required files were copied into a private mode-700 temporary input root and re-read through typed readers before the provider call.

## Complete lineage snapshot

```text
forbidden_candidate_count=52
forbidden_candidate_snapshot_sha256=08887ae808bd9afeaf5091047b52e3541066005455d2b75080f492a04fddfcae
```

The snapshot included historical provider IDs, canonical IDs derived from historical persisted strategies, and the two protected recent candidates.

## Provider attempt

```text
campaign_id=creator-batch-20260902-008
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
content_length=1504
content_sha256=71dac92cb64e474e6311d01901b164d3c55ab67eff31fd1ee1ecfec84adb5ca1
generation_decision=accepted
generation_reason=schema_valid
thinking_level=minimal
include_thoughts=false
response_format=json_object
```

Raw prompt and raw provider response were not persisted.

## Candidate

```text
candidate_id=cand-148b5e15c0985f8e513f20636d8330822198c63759f95a946e866c90723291ad
candidate_artifact_hash=d1955931522fe61c0c45052b17bbb1b1afebe92af6b7bddf887fa47f8953f744
candidate_registry_hash=cb6484a08a5df1fc6ed0f056bb160684cf0bafba4e7b7f53ca7856b45f7fc4f9
state=testing
family=range_mean_reversion
```

Strategy contract:

```text
features:
- bollinger_zscore lookback=20 shift=1
- adx lookback=14 shift=1
- rsi lookback=14 shift=1
long_entry=bollinger_zscore < -2.0 and rsi < 30.0
short_entry=bollinger_zscore > 2.0 and rsi > 70.0
long_exit=bollinger_zscore > 0.0
short_exit=bollinger_zscore < 0.0
veto=adx > 25.0
position_fraction=0.2
stop_atr_multiplier=2.5
take_profit_atr_multiplier=3.0
trailing_atr_multiplier=1.5
```

## Cached OOS result

```text
windows=4
trades=1989
pooled_profit_factor=0.5153807339704021528941012538
average_return_pct=-13.10716410755228999680951970
worst_drawdown_pct=16.44619950326416414080152216
aggregation_hash=456e2ab10b2281e913dec7fd5d204233563606cb520231b4cf21530934183209
```

Compared with the rejected Phase 237 trend revision:

```text
profit_factor: 0.4407645772 → 0.5153807340
average_return_pct: -40.02864382 → -13.10716411
worst_drawdown_pct: 44.22577089 → 16.44619950
```

The new family materially improved all three headline metrics but remained loss-making and below every quality/risk threshold.

## Qualification

```text
decision=rejected
qualification_hash=123013842743c52dfbd6dc1894bb0e8b611a3b5336a34bc5b419fd7c646a3587
failed_gates:
- oos_average_return_below_threshold
- oos_drawdown_above_threshold
- oos_profit_factor_below_threshold
- oos_symbol_average_return_below_threshold
- oos_symbol_drawdown_above_threshold
- oos_symbol_profit_factor_below_threshold
```

No gate was relaxed and no negative evidence was overridden.

## Immutable evidence

```text
file_count=6
evidence_snapshot_sha256=42cd991828771a4a68381ba09129e8346f98cf9e3535f2d3b78175a4fe3cef9a
campaign-summary.json=e8a2fcc0db0784af82df2ef46c71ecb262dfd774542463d9666121dab52ae5d5
candidate-registry.json=bd3e32cb279d684e99055e9881fdfe28bfc31fcbb254232190b485ce5171193b
candidate=33c74180b348035f1025768b09031ec619da8b179dd8a78aae2f845be3159cde
oos=da009ea597e3bc4c0815d7d6245bd48df0897cf641bd51286187538984e92ee7
qualification=ebafb2a78f2a7124b9bc8cda845a0be4a8172ebd24c213a5eecd460ecf25b29e
trial=ab2b2b987d64a6bd98e941be964b9c1d76b7b42c0c31d90b1a0be2a50abc764e
```

Every trial, candidate, registry, OOS, and qualification artifact was independently read through its shared hash-verifying reader.

## Safety and cleanup

```text
provider_requests=1
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
unit_load_state=not-found
research_timers=0
remote_transients=absent
local_transients=absent
```

## Boundary

This campaign is complete and rejected. Do not promote, activate, relax gates, or blindly retry it. Because the materially new family improved substantially over the closed trend family while remaining negative, the next bounded decision-changing slice may use this exact persisted rejection for one Critic-guided `range_mean_reversion` revision. That would require a separate provider request and separate approval.
