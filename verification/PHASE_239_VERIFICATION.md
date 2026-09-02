# Phase 239 Verification — Bounded Range-Family Critic Revision

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **CLOSED / REVISION-REJECTED / LINEAGE-PREFLIGHT-GAP**

## Scope

Use the rejected Phase 238 `range_mean_reversion` evidence for exactly one Learner/Critic review and, only after typed readback showed an actionable representable review, exactly one Creator revision. Reuse the existing provider, strict schemas, canonical candidate identity, immutable writers/readers, cached OOS evaluator, and unchanged qualification gates.

```text
runtime_model=gpt-5.6-sol
runtime_provider=openai-codex
runtime_effort=Medium
remote_provider=google_ai_studio
remote_model=gemma-4-31b-it
```

No production code or dependency was added.

## Exact-source preflight

```text
source_commit=1f34f09d2e385af4b52bf3b9ff892387c3de5342
critic_runner_sha256=4dce9e63d07f2f18529e001cb619d1322bf070e426bbdf41e72c492e45480e63
creator_runner_sha256=8e3efb9d559a278ba9a86a8dd96aa32d59f4637afcae78c04d3f6fcc54e40660
source_archive_sha256=9105bc4cbc96fcadbd3a7c2eda1ab7d3d2bdbb948779114ae131deea3dd7bf33
provider_source_sha256=a8cde3b33d401a00cdfcfa0653733f6f6e859be64a96682a5da9714c5fcc36cb
focused_tests=31 passed
```

The first full-repository archive upload timed out before any remote runner or provider call. The partial upload was deleted and replaced with an exact-commit archive limited to the tracked runtime source and lock manifests. This was transport recovery, not a provider retry.

Protected Phase 238 candidate and qualification files were copied to private mode-700 input roots and re-read through shared typed readers.

## Source binding

```text
source_candidate_id=cand-148b5e15c0985f8e513f20636d8330822198c63759f95a946e866c90723291ad
source_candidate_artifact_hash=d1955931522fe61c0c45052b17bbb1b1afebe92af6b7bddf887fa47f8953f744
source_qualification_hash=123013842743c52dfbd6dc1894bb0e8b611a3b5336a34bc5b419fd7c646a3587
source_family=range_mean_reversion
required_feature=bollinger_zscore
```

## Critic request

```text
campaign_id=critic-campaign-20260902-009
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
content_length=691
content_sha256=e85b6d714525f626a8b49070bcf9009e281e25770fb5b842c3306e0671a5f675
result_decision=accepted
critique_decision=revise
```

Typed Critic evidence:

```text
evidence_hash=b01081d7a5cbe0dad2f434c099aad327035151f382cb77c3e4c1055b2290ad73
review_hash=28e6bb1bb63b78a8e7584cd46905ffc5a3ae7dff6492960f89e53296f27fefdf
revision_actions:
- adjust_atr_stop_multiplier
- adjust_target_multiplier
- optimize_position_fraction
- optimize_trailing_multiplier
```

All actions passed the existing representability and forbidden-authority preflight before the Creator request.

Critic immutable files:

```text
critic-evidence.json=0252bab0f7897b0b1c6ebf9427ccf69a9baf5255cdc4895f3e74c264a8ac0582
critic-summary.json=4932d19b7d557799014e1d457eb3332c2748eda97062600611e9f7a94e31c183
critic_snapshot_sha256=c4c94eba58ab3045766be6ddb5b690a6901ca51d912a755527eb79a79cf35018
```

## Creator request

```text
campaign_id=creator-batch-20260902-010
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
content_length=1652
content_sha256=af276df291aadeccee443a952fcb0955aecc8a85900ce46d1e9fb97e7016c6c5
generation_decision=accepted
generation_reason=schema_valid
```

The operational guard required `range_mean_reversion` plus `bollinger_zscore` before persistence.

## Revised candidate

```text
candidate_id=cand-febf9237c4a904eda69fb122083bc2f1297640d2094cd7844bb5caa906d014f4
candidate_artifact_hash=f7cc46a5e1163a6921b63136b287dd08287299582e5c8484ce27c4f60ab1fe99
candidate_registry_hash=d322304efe9e3b373d39eff101572beb793d658853f8b379d1a2f86fa2b7d909
state=testing
family=range_mean_reversion
```

The revision retained `bollinger_zscore`, replaced the ADX feature with `regime_trend`, retained RSI, and reduced `position_fraction` from `0.2` to `0.1`. Stop, target, and trailing multipliers remained `2.5`, `3.0`, and `1.5`.

## Cached OOS comparison

```text
metric                 Phase 238 source       Phase 239 revision
windows                4                      4
trades                 1989                   1989
profit_factor           0.5153807339704022     0.5152104765184188
average_return_pct     -13.10716410755229      -6.784165070534109
worst_drawdown_pct      16.44619950326416       8.582957825223537
```

The lower exposure roughly halved return loss and drawdown, but profit factor marginally worsened and remained far below `1`. This is not qualification evidence.

```text
aggregation_hash=38e166902fa98bbcda7f384139754a9d8db5a61266bc318a104f56e828e4d23d
qualification_decision=rejected
qualification_hash=3a8ae6ea0d60cb780d58dbef9ccccd5731af6e525dfab38c7fba7135f2ad6660
```

Failed gates:

```text
oos_average_return_below_threshold
oos_drawdown_above_threshold
oos_profit_factor_below_threshold
oos_symbol_average_return_below_threshold
oos_symbol_drawdown_above_threshold
oos_symbol_profit_factor_below_threshold
```

No gate was relaxed or overridden.

## Creator immutable evidence

```text
file_count=6
evidence_snapshot_sha256=0bcc7ba4f8be9b051a5681ae9bfe87c9ca8521418a34cc532c06a6dc6e1f9ae0
campaign-summary.json=863d8b3ae3600531fe031b622e959ca7e032f8baadc31bd0349db294bd9a337c
candidate-registry.json=0a455f9f1f56a7896464dfc0eaaa6f3f95d99332c7893a74d7c7bdfe724bf01f
candidate=bd4670b91e3a1cc07b3d4650fae2aeb5cf6ff8bb0bf5d94cfeaab405696d4326
oos=ee220ebaf7858877be5402256514cd64e89ced50e862d376074cc235cbf59075
qualification=48a17be3d692cc45c3ddab1ddb355a4cce3a77f49ad420cf211bc5f9be5cd737
trial=f06c1324c41c002a44429194e2db23d5bce6b44d7adba6e62afe787e1cb004cc
```

Candidate, registry, trial, OOS, qualification, and Critic evidence were independently read through shared hash-verifying readers.

## Lineage preflight gap

The Creator runner recorded:

```text
forbidden_candidate_count=51
forbidden_candidate_snapshot_sha256=69880a5dbde8bd669baac8a74a84c65012db5093cf643613021557b9b2cf4631
```

The operational snapshot used the historical root plus the immediate Phase 238 source candidate, but did not stage the known recent Phase 236 and Phase 237 candidates into that pre-request snapshot. That violates the complete historical-lineage preflight contract even though independent readback proved the returned candidate ID differs from all three known recent candidates.

Therefore this phase is explicitly marked `LINEAGE-PREFLIGHT-GAP`, not a fully audit-clean Creator lineage result. No provider rerun was made because both approved requests were already consumed and the candidate was qualification-rejected.

## Safety and cleanup

```text
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

## Boundary

The `range_mean_reversion` same-family loop is closed. It remains loss-making, profit factor did not improve, qualification failed, and the pre-request lineage snapshot was incomplete. Do not run another Critic/Creator retry, relax gates, promote, activate paper, or execute orders. A future Creator campaign must first stage the complete recent typed candidate history into its forbidden snapshot and must use a materially different falsifiable family.
