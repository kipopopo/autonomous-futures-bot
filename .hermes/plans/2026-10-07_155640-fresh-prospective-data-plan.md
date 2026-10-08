# Fresh Prospective/Independent-Data Cycle Plan

> **Archived planning snapshot — Antigravity takeover, 2026-10-08:** Read [ANTIGRAVITY_HANDOFF.md](../../ANTIGRAVITY_HANDOFF.md) in the repository root for current authority and ownership. After this plan, the owner selected one Segment B historical-screening cycle (one Critic / one Creator / one evaluation, no GET/retry/tuning/promotion/trading); it was not executed. The older unused-window condition below failed and remains distinct from that later screening selection. Use the already-approved protected fresh-epoch branch, not impossible reconstruction of historical acceptance or a disabled legacy gate. This plan remains future-data/confirmation planning only: no acquisition approval, provisioned provider permit, service change or trading permission follows from it. Antigravity is the next sole writer; Hermes does not execute this plan after transfer.

**Goal:** Establish one immutable, prospectively isolated strategy-confirmation cycle without mislabeling previously used Segment B data as an untouched holdout.

**Architecture:** Separate candidate development, pre-registration, public-data acquisition, and one-shot confirmation. Reuse the verified data bundle/funding loaders and simulator v4; add only the missing explicit-scope acquisition and confirmation-runner seams after their approvals. Preserve existing qualification thresholds and keep promotion, paper, testnet, live, and orders disabled.

**Tech Stack:** Python 3.14, `uv`, pytest, Ruff, mypy, existing Binance USD-M public collector, Parquet manifests/registry/bundle, `VerifiedFundingSlice`, and funding-settled simulation v4.

---

## Current facts and constraints

- Current pushed source: `7fc698b0564b8e7981e416a941a8e5952b413bd8`. Exact-SHA Actions `37642230850` passed: **5,169 passed, 1 skipped, 2 warnings**; Ruff, formatting, strict typing, and compile passed. The branch was clean at that SHA.
- Segment B is complete, but not an unused holdout. `research/strategy_screen.py` used `[2023-01-01, 2025-01-01)` for training, 2025 for validation, and 2026 YTD for testing; `research/strategy_screen_results.json` confirms actual funding was included. This covers Segment B's full `[2023-11-10T04:15Z, 2026-08-06T05:30Z)` span. The proposed 2024-01 windows are therefore prior training/selection evidence.
- The prior one-shot Segment B approval was conditional on an auditable unused window. That condition failed; the approval remains unspent and does not authorize a reclassified screening run, another provider request, or another GET.
- Commit `7fc698b` adds a research-only 5m `funding_rate` event feature bound to a verified funding slice. Rates map to their containing bar, are delayed by the declared positive shift, remain null between events, and are not forward-filled. There is no accepted candidate or performance result from this feature.
- The collector is still bounded by `APPROVED_END_MS_EXCLUSIVE` at 2026-08-06 05:30Z and `MAX_PUBLIC_GETS=1,800`; those constants and the old approval do not authorize future collection. The existing prospective protocol is a draft, not an acquisition or evaluation permit.
- The existing draft windows `[2026-10-12, 2026-11-02)` may only be considered if they remain wholly future and an accepted candidate plus protected preregistration are completed before the first context bar. If any gate is missed or any price/context is observed, abandon those dates and select later windows before observing them.
- Notional is fail-closed at 5.00 USDT; venue minima BTCUSDT=50, ETHUSDT=20, SOLUSDT=5 USDT. Do not raise the cap or bypass venue minimums. A BTC-only confirmation can be research evidence but is not executable at that cap.

## Plan

### 1. Resolve the candidate-development source before any provider call

- Choose whether candidate development uses previously seen Segment B strictly as **training/screening evidence** (never untouched/OOS), or a separately approved independent training source.
- If Segment B is selected for screening, obtain a new explicit one-shot budget and state the non-OOS label, exact source SHA, candidate family/feature contract, one Critic, one Creator, one evaluation, zero retries/fallback/tuning, and no promotion. Do not reuse the old conditional approval.
- Require a complete verified lineage snapshot and collision-free candidate ID before credentials or transport. Candidate acceptance must use the existing thresholds unchanged; failure is retained and ends the budget.
- Freeze one accepted candidate, its qualification/policy, source bundle/registry, exact artifact hashes, dependency-lock hash, risk/cost settings, and evaluator SHA. A schema-valid or persisted candidate alone is not accepted.

**Gate:** No candidate is eligible for future confirmation until all bindings are verified and the owner approves the exact research scope. If no candidate passes, stop; do not start a holdout collection.

### 2. Revalidate and pre-register future dates

- Read the protocol's future intervals and current UTC time immediately before registration. Keep the October draft only if no interval/context has begun and all freeze requirements can be met before its first context bar; otherwise choose a later contiguous set of three non-overlapping half-open windows.
- Bind one symbol, venue, intervals, timezone, per-window resets/continuous-equity choice, warmup rule, fill latency, starting equity, fees, slippage, force-close behavior, and exposure limit.
- Compute warmup from the frozen candidate's declared features. Load only prior closed bars for warmup; exclude warmup trades and P&L. Reject unsupported lookbacks rather than truncating silently.
- Record the candidate/qualification/source hashes, exact temporal exclusions, and the existing policy thresholds in a protected preregistration. Treat the proposed additional confirmation verdict as a separate policy requiring owner approval; do not silently modify the qualification gate.

**Gate:** Protected preregistration readback must succeed before any context observation. Ordinary filesystem writes and hashes alone are not operator protection.

### 3. Define a new acquisition permit and collector scope

Before collection, prepare a separate approval request containing:

- Exact half-open scored ranges plus required warmup/context range.
- Symbols, 5m primary/15m context intervals, and allowed public unsigned endpoints only: `klines`, `markPriceKlines`, `fundingRate`, and one `exchangeInfo` snapshot.
- Deterministic per-endpoint page counts, total hard GET cap, no retry/resume, stop-on-first-error behavior, local-only destination, immutable root, and retention rules.
- Funding/mark-price provenance policy, expected complete coverage, and explicit `UNAVAILABLE` treatment for any gap or incomplete artifact.

The current collector cannot fetch future ranges. After explicit acquisition approval, add the narrowest scope interface that preserves the old historical constants and rejects any request outside the newly approved manifest. Preflight the complete page budget before the first GET. Do not perform a smoke request, inspect future prices, or collect any rows while preparing this plan.

### 4. Build the missing confirmation runner only after scope approval

- Reuse `load_verified_cached_evaluation_window`, `VerifiedFundingSlice`, funding simulator v4, and the existing `confirmation_evidence.py` envelope; do not bypass the ordinary candidate-scope guards or rewrite the candidate to fit a new bundle.
- Add a bounded runner that loads the protected frozen candidate and separately verified future bundle, enforces exact symbol/window/hash bindings, applies warmup without scoring it, and evaluates each window once.
- Bind the effective simulator/configuration and native trade/equity outputs to independently read-back provenance receipts. A missing input, integrity error, interruption, or publication failure is `UNAVAILABLE`; never retry, tune, or synthesize zero results.
- Keep confirmation provider calls at zero. Preserve all outputs unpromoted and execution-disabled.

### 5. Prove the path offline before any GET

Use synthetic fixtures and injected files only; do not use the actual future market data in tests.

1. RED/GREEN tests for explicit future-scope validation and preflight rejection before transport.
2. Tests for verified bundle/registry/artifact bindings, exact funding event mapping, no forward-fill, prior-bar causality, warmup exclusion, half-open boundaries, and future-row mutation not changing earlier signals.
3. Tests for one evaluation per window, no retry path, unavailable/partial evidence, immutable output/readback, and unchanged candidate hashes.
4. Run focused/related tests, lock check, Ruff, formatting, mypy, compile, diff and secret scans; commit/push only the verified code. Require exact-SHA CI before requesting any acquisition approval.

Likely files after approvals: `scripts/collect_approved_public_data.py` (or a narrowly scoped companion), `src/autonomous_futures/research/cached_evaluation.py`, `src/autonomous_futures/research/confirmation_evidence.py`, a bounded confirmation runner, and focused collector/confirmation tests. Do not change files during this planning-only step.

### 6. Execute only after separate approvals

After exact-source CI and all protected freeze checks pass, request a distinct public-data acquisition approval with the exact manifest and hard GET cap. Collect once after all scored bars close, verify every component through canonical readers, and publish the immutable bundle. Then perform exactly one confirmation evaluation per frozen window, with no provider calls, retries, fallback, tuning, or strategy changes. Read back all evidence and report pass/fail/inconclusive/unavailable without promotion or operational activation.

## Stop conditions and open decisions

- Segment B cannot be used as untouched/OOS evidence.
- No accepted candidate currently exists; candidate-development authority is separate from future data-acquisition authority.
- Confirm whether the October draft dates are still fully future when all gates are ready; otherwise replace them before observation.
- Select symbol(s) without weakening the 5.00 USDT limit or bypassing venue minima.
- Set a new exact GET cap only after the final dates, warmup, symbols, and endpoint page plan are known and approved.
- No provider call, GET, SSH, VPS/service change, paper/testnet/live activation, or order is part of this plan.
- Even a successful confirmation does not establish generalization, legal/account/capital readiness, production readiness, or permission to trade.
