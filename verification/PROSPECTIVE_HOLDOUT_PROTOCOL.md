# Prospective confirmation holdout — draft, not execution permission

Status: offline protocol drafted on 2026-10-05. No eligible frozen candidate, acquisition for the declared prospective windows, holdout evaluation, operator-protected preregistration or operational permission exists for this protocol. A separately approved historical public-data attempt for `[2023-01-01T00:00:00Z, 2026-08-06T05:30:00Z)` failed after two GETs and does not satisfy this protocol's future-window acquisition gate. This document does not confer paper/testnet/live authority.

## Existing evidence remains unchanged

- `cycle-epoch-a1b4e68-001` remains rejected and unadmitted; its spent provider/OOS budget is closed.
- Its historical windows informed the revision. They remain research/selection evidence, irrespective of the saved `walk_forward_oos` label.
- Do not rerun that evaluation to fill missing window ledgers, import legacy acceptance history, copy its qualification to a new scope, or mutate its candidate/bundle/registry bindings.
- The new persistence path applies only to future separately authorized cycles. Historical missing ledgers remain missing.

## Prospective scope proposed before observing outcomes

One BTCUSDT, Binance USD-M futures, 5-minute confirmation campaign; three nonoverlapping UTC windows, all half-open:

| Window | Scored range |
| --- | --- |
| `holdout-20261012` | `[2026-10-12T00:00:00Z, 2026-10-19T00:00:00Z)` |
| `holdout-20261019` | `[2026-10-19T00:00:00Z, 2026-10-26T00:00:00Z)` |
| `holdout-20261026` | `[2026-10-26T00:00:00Z, 2026-11-02T00:00:00Z)` |

These are planned future intervals, not collected or verified datasets. Use only prior closed bars for each window's feature warmup; no warmup trades or warmup P&L may enter scored metrics. Require a supported explicit warmup bound and tests proving that future rows cannot alter earlier signals. Reject unsupported lookbacks rather than silently truncating context. Do not shorten or move the range after viewing prices or results. If preregistration misses the first context bar, abandon this draft range and preregister a later prospective range before observing it.

## Freeze gate before first context bar

Before any holdout/context observation, retain a separately protected, independently read-back registration containing:

1. Exact CI-passing evaluator source SHA and immutable dependency-lock hash; evaluator version alone is insufficient.
2. One genuinely accepted fresh-epoch candidate's immutable artifact hash, unchanged StrategySpec, source training bundle/registry, acceptance sequence/head and protected reader pins. The current rejected candidate is ineligible. No family tournament, best-window selection or synthesized Creator authority.
3. The exact research qualification artifact/policy and all thresholds. Keep the existing approved research gate unchanged; passing it is not a holdout verdict.
4. The three future intervals, exchange/timeframe, timezone, warmup/context rule, fill latency, sizing, starting equity, fee/slippage and force-end-of-window rules; explicitly distinguish independent window resets from a continuous equity account. Preserve the hard 5.00 USDT exposure limit wherever it applies. A fee-free or minimum-notional-bypassed simulation is not proof of executable sizing.
5. Training/selection/exclusion intervals and artifact hashes; prospective isolation plus this audit is required. Hashes alone do not prove that data was unseen.
6. Budgets: one fixed-candidate confirmation campaign, each window evaluated once; zero provider calls during confirmation, no retry/fallback/tuning. Missing input, integrity failure, interrupted evaluation or ledger-publication failure stops the campaign with retained partial evidence; it does not mint a second budget.
7. Unchanged qualification/adoption separation and the additional confirmation rule below, approved before prices or results are inspected.

New market data has different immutable scope hashes. The existing cached-OOS and window-evidence writers deliberately reject a foreign candidate scope. **Do not bypass those guards or rewrite a Creator candidate to fit holdout data.** The separate `confirmation_evidence.py` observation envelope now preserves the unchanged original candidate/training hashes, exact qualified research artifact hash, distinct evaluation window scope, supplied native trade/equity result and declared simulation configuration. Its reader verifies the original source bindings and its writer shares no-clobber persistence with ordinary window evidence; ordinary OOS scope guards remain unchanged. This is **observation-only**, not an operational confirmation runner: epoch acceptance, preregistration and untouched-isolation flags are fixed false, as is execution authority. Self-hashes and qualified labels do not prove protected acceptance, policy adjudication, effective simulator/configuration or unseen data. Actual confirmation still requires the separately protected freeze gate above, approved acquisition, a bounded evaluator with tested context/warmup/exclusion semantics, independent configuration/provenance receipts and the preapproved confirmation verdict below. No actual holdout evaluation or eligible candidate is created by this software contract.

## Acquisition and evidence gate

Data collection needs separate bounded approval. Permit only public, unsigned market-data retrieval for the declared ranges after bars close; no account, position, credential, order, service or provider access. Retain immutable source responses, retrieval observation times, exact OHLCV/price definitions, pagination/completeness/gap/duplicate checks, canonical dataset manifests and integrity hashes. An incomplete window is UNAVAILABLE, not a losing or zero-return substitute.

The future research cycle now saves, before qualification:

- `evaluations/eval-<cycle-id>.json`: the existing typed aggregation, including all per-window metrics and the aggregation hash referenced by qualification.
- `evaluations/eval-<cycle-id>/<symbol>/<window-id>.json`: native trade/equity result, cached window spec, original candidate ID/hash, and canonical envelope hash. Candidate scope and timeframe must match; trade/equity timestamps must stay inside the half-open scored window. Outputs are unpromoted and execution-disabled.

Publication uses unique fsynced temporary files and no-clobber hard links, with typed readback. Conflicting content cannot replace an existing target; identical content is idempotent. Filesystem errors fail closed and clean temporary files. Accepted reservations and already published evidence are retained on downstream failures. Ordinary filesystem publication is **not** operator protection, power-loss-proof directory durability, or independent market provenance. Hosts without supported hard links must stop, not fall back to overwrite.

For actual confirmation, retain all native per-window ledgers plus exact effective simulation configuration and operation/provenance receipts. The current ledger envelope does not itself attest which injected simulator/source/configuration ran. Protect the receipt binding all output hashes and verify it as the runtime reader. Recompute statistics from saved trades/equity only, then compare every window and aggregate to the saved qualification; do not rerun signals or trades. Explain unmatched/incomplete evidence as UNAVAILABLE. Synthetic fixtures demonstrate this software path, not future market outcomes.

## Proposed independent confirmation verdict

These are draft additional confirmation criteria, not edits to existing policy: all three complete windows present; at least five scored trades per window; no negative net return in any window; pooled profit factor at least 1.05; worst window drawdown no greater than 15%; and no configuration, strategy, cost or data-boundary change between windows. A result missing sufficient losses for a defined profit factor is inconclusive rather than an invented infinite value. Any integrity/isolation failure is UNAVAILABLE; a complete failure is rejected; insufficient sample is inconclusive. Passing these small-sample criteria would still not establish generalization, live profitability, account suitability or production readiness.

Retain all results, including zero-trade, rejected, inconclusive and partial outcomes. Do not extend the sample, retune parameters, switch family, choose a new seed, drop a poor window or reuse observed confirmation data while still calling it untouched. Observed data may subsequently become explicitly labelled research data only under a new bounded approval and a later untouched confirmation range.

## Gates remaining after confirmation

A successful confirmation is only evidence for subsequent review. Continuous protected writer/reader scheduling, monotonic pin advancement, paper admission/execution/verified ledger feedback, restart/reconciliation observation and separate operational rollout remain required. Testnet/live additionally require explicit legal/venue/account/capital/secret-manager/kill-switch/current-reconciliation approval. No automatic activation or order follows this document or a passing test suite.
