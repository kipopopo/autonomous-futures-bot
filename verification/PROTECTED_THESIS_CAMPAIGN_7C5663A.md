# Protected thesis campaign — stopped by an invalid local family pin

## Outcome and responsibility

Explicit approval: `Lulus pakej one-shot research-only SHA 7c5663a`. Executed source: `7c5663a2603d29b08d6f327115ae469106eeda1b`; exact-source Actions [37260609314](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/37260609314), job `111606851510`, passed **5,020 tests, 1 skip, 2 warnings in 899.44s**, plus lint/format/types/compile.

Cycle `cycle-epoch-7c5663a-001` used **one Critic and one Creator request**, both HTTP 200, with no retry/fallback. It returned `failed` / `family_contract_mismatch`. **No new candidate, accepted proposal, cached evaluation, qualification, paper admission or order was produced.** The Critic evidence is retained; raw Creator output is not retained and must not be reconstructed or guessed.

The failure was caused by the assistant-authored operational wrapper, not an observed lack of economic edge: it required `strategy.family="failed_breakout_reentry"`, but the native `StrategyFamily` literal and canonical Creator prompt do not permit that family. `failed_breakout_reentry` is an evaluator feature. Therefore any schema-valid proposal necessarily failed the local family guard. The three namespace-shaped guard checks passed but did not validate representability through the actual domain schema. This was an inadequate preflight and consumed the approved provider budget unnecessarily; do not describe it as a market qualification rejection or provider schema failure.

A subsequent **offline-only native check passed four cases**: the invalid feature-as-family is rejected by `StrategySpec`; a supported `range_mean_reversion` strategy with the causal `failed_breakout_reentry` structural marker satisfies the guard; wrong family and missing marker fail. The supported family also appears in the canonical prompt. These are synthetic contract checks, not an accepted Creator candidate. No domain enum was expanded, executed runner altered, historical evidence rewritten or provider request repeated. Before any future call, apply this native representability check to a new reviewed wrapper and obtain a new explicit budget; this report does not authorize that call.

## Verified staging and prerequisites

- Protected create-only source staging: **360 files**, manifest SHA-256 `f3a8d65547176927e4c0490e72cc4d9522e8d6371d5eca0e34fcf766d5e6b52f`; archive SHA-256 `90581314bcdc37fd0ba032cae4f490a3034cdb4536d9767dbc8c37653989b64e`.
- Network-isolated smoke ran as actual runtime UID 1001 using the reused locked Python **3.14.7** runtime: **357 source files compiled**, **51 locked distributions checked**, imports from the exact protected release. No dependency installation or existing-service activation.
- **39 exact seed/cache files** were staged and hash-checked. Actual writer UID 1000 verified the prior Creator candidate and rejected qualification, **13 market components**, **3 cached windows**, original candidate/scope/qualification bindings and fresh-epoch membership at sequence 1, before credentials/provider calls. Old missing window ledgers were not reconstructed and the baseline was not reevaluated.
- Input candidate hash: `5b75f6df0eb0762322fb9555a52003fd9006edebb34627fe295f0a56c968f48f`; qualification hash: `c197e7a845f15c47908f1eeb0d2eadc03ffa092f839cf850887bfd4cc61292f7`. Both remain the prior rejected research result, not holdout or paper-ledger feedback.

## Authority, retention and cleanup

Fresh epoch `epoch-fresh-20261003-001` stayed at **sequence 1 → 1** with head `53313c6e237e812d521559a2afbc74947a04277a170978d916b0bc7e11e87f43`. No monotonic pin advancement was needed. Actual runtime UID 1001 independently verified journal/control/protected checkpoint agreement and **six kernel write denials**. This preserves the previous single acceptance, not a new acceptance or continuous-writer proof.

The one-shot unit was collected; its decrypted runtime credential directory and runner/argv were absent. The grant was closed and spent precredential reservation retained. Exact existing-service PID/restart/state snapshots were unchanged. Publication removed this campaign's temporary outputs and inputs after protected retention; local temporary seed copies were removed separately. The protected inactive source and immutable receipts remain. There was no data acquisition, service restart/resume, account query, paper activation, testnet/live or order.

Protected publication observed at `2026-10-05T04:34:00.263788+00:00` retained **8 typed/observation JSON artifacts** and exported **14 evidence/receipt/pin files**. Local verification at `2026-10-05T12:40:37.787372+08:00` rechecked all eight publication hashes, counted 14 retained JSON files (including local receipt files, not a total-file count), read the native Critic evidence and exact prior candidate/qualification bindings, checked no candidate/evaluation files and confirmed the unchanged checkpoint. Local receipt consistency is not a later remote-state attestation.

Evidence is outside Git under `../Autonomous Futures Bot Evidence/epoch-research-7c5663a-001/`: `source-staging-receipt.json`, `inputs-verify.json`, `operation-setup.json`, `operation-verify.json`, `retained/operation-receipt.json`, `retained/evidence-publication-receipt.json`, and `retained/evidence/`. Three procedure files are retained under `procedures/`; the as-executed runner hash still equals the setup receipt: `25ae24c0794d7c55fa9823779516f4e97246e024da1564220446869d6ff7197c`. Retain the invalid executed pin as evidence; do not replace it with the corrected offline fixture.

## Remaining boundary

The real campaign did not exercise the new per-window persistence path because it stopped before simulation. That path has canonical native/real-CLI synthetic coverage and exact-source full CI, not a new real-market ledger outcome. The existing candidate remains rejected; no eligible frozen candidate or untouched confirmation exists. `verification/PROSPECTIVE_HOLDOUT_PROTOCOL.md` remains a draft, with cross-scope confirmation provenance still unimplemented and no data/holdout permission.

**Project NOT PRODUCTION READY.** The consumed grant cannot be reopened or reused, and an unused downstream evaluation allowance cannot manufacture a new Creator candidate. Further provider work requires a newly reviewed, representable campaign and separately explicit budget. Autonomous protected scheduling, genuine qualification → paper execution → verified feedback, reconciliation/rollout and legal/venue/account/capital/secret-manager/kill-switch/live approvals remain outstanding. Passing CI or this safely stopped campaign does not close them.
