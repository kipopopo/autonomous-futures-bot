# Offline fresh seed and rejected-OOS cycle boundary

## Scope and outcome

The owner approved one offline fresh operator-authored baseline and one cached OOS evaluation, then paused work and explicitly resumed it. This approval did not include provider requests, credentials, remote writes, real epoch acceptance, paper admission or trading. The baseline was evaluated once; its rejection is retained without tuning or retry.

**Outcome: rejected. Project status: NOT PRODUCTION READY.** The rejected qualification is a typed research seed, not paper-ledger feedback, Creator output, acceptance history or execution authority.

## Retained evidence

Durable local directory, outside source/runtime/history discovery roots:

`../Autonomous Futures Bot Evidence/offline-bootstrap-20261004-001/`

It contains the operator candidate, policy, three simulation results, aggregation, qualification, feedback projection, receipt and retained `bootstrap_procedure.py`. The procedure's `--verify-only` path reads existing artifacts and reconstructs qualification gates from the saved aggregation; it does not rerun the backtest. Do not invoke its evaluation path again under this approval.

- Original evaluation observation: `2026-10-04T14:15:49.069536+00:00`.
- Candidate: `cand-operator-btc-seed-20261004-001`.
- Candidate source/state: `operator_authored_research` / `testing`.
- Candidate hash: `fbd960757e82179de4b8a4c7751c4830da3c79abd389a99b3f7d0c8b0f32df71`.
- Bundle hash: `07a654ebcaa6c40d4399e744ad05a5dee77e4ec61bac2743a2f17380324de7dd`.
- Registry hash: `625c0558b79913d98f5f08c5e44f263b0822e0e1b5588bf4dbdf6147fbe680c4`.
- Aggregation hash: `8efb95a698807e6a91a09dc542f20224e9cfcb9142e25006a82ee73058112cb0`.
- Qualification hash: `bd92ecdd4587dc3dcc7c57970c1cc946494e117ec4811d771320318991c0daaf`.

The fixed baseline uses BTCUSDT 5m shifted returns (lookback 3, shift 1), symmetric +/-0.001 entry/reversal thresholds, 0.10 position fraction and ATR stop/target/trail multipliers 2/3/1. It was frozen before evaluation. The existing cycle policy remained unchanged: minimum 1 window, 5 trades, profit factor 1.05, average return 0%, maximum drawdown 15%.

Three consecutive 288-row windows cover `[2026-09-10T01:15Z, 2026-09-13T01:15Z)`. The result has **89 simulated trades**, pooled net P&L `-1.117777162048676142999316087`, profit factor `0.1867505564892595034644658377`, average window return `-0.3725923873495587143331053623%`, and worst window drawdown `0.6321285591935929581866642812%`. Global and BTC average-return/profit-factor gates failed. These are unlevered simulation metrics with separate 100-unit starting equity per window, not a live account return.

The receipt records 13 verified market components, unchanged input bytes, zero network attempts/provider requests, zero epoch acceptances, no paper ledger, no paper activation and no orders. Fresh clean-environment `--verify-only` execution returned exit 0: shared typed hash readers, reconstructed qualification equality, source snapshot parity, three simulation records, trade-count consistency and disabled authority passed. This is local retained-evidence consistency, not a fresh VPS observation or proof of historical acceptance. The evaluator version label `cached-oos-45ef79e` is not an exact-source attestation: the evaluation used that base plus the uncommitted operator-source extension.

## Minimal implementation

- `creator_artifacts.py` preserves the new operator-authored source explicitly; existing Creator artifacts retain their original default and hashes.
- `run_autonomous_cycle.py --qualification-path` requires a paired hash-verified rejected walk-forward qualification and candidate. Candidate ID/hash, bundle/registry and symbol must match. Mixed paper/JSON inputs, non-OOS/empty/qualified/tampered evidence and unprotected provider invocation fail closed.
- The route reuses `build_creator_qualification_failure_feedback`; it never fabricates a ledger or constructs a paper engine. Its audit identifies `walk_forward_oos`, and its result has no active candidate or admission.
- Provider permits allow exactly one ledger source or a qualification path **and hash**, never both. OOS permits exclude lifecycle state. Exact source/pins/writer/expiry checks and durable one-shot budget reservation remain intact. Source artifacts and protected grant are rechecked before credentials and before/after each transport.
- The pipeline reuses the existing configured admission decider as a research-only epoch writer without a paper runtime. Existing accepted-ID snapshot and atomic acceptance-before-persistence remain unchanged. Rejected/qualified research results cannot adopt or publish a paper candidate.
- This adds no provider grant, scheduler mode, API, dependency, strategy tuning or trading capability. Legacy history remains unavailable and unmodified. A hash verifies contents, not independent evaluator provenance; only a separately approved protected grant can authorize the exact operator-supplied research source.

## Verification

Initial operator-source and OOS-route regressions were RED in the preceding interrupted work; the resumed current tree passed:

- 30 permit/OOS tests in 5.53s before additional adverse coverage.
- Final nine-module affected regression: **129 passed in 120.00s**, including actual CLI/injected HTTP, real SQLite reservation and persistence, both ledger/OOS sources, bad source/hash/expiry/identity, acceptance rollback, in-flight revocation/source removal and budget reuse rejection.
- Ruff lint and formatting using the workflow roots `src tests research scripts`: passed, 711 formatted files.
- Strict mypy `src scripts`: passed for 356 files on both Windows and Linux targets.
- `uv lock --check`, `git diff --check`: passed.
- In-memory Python compilation: 710 files passed. This does not claim Windows bytecode-writing `compileall` passed; Linux CI runs that command.
- Independent read-only safety review returned no actionable findings. It did not run tests, verify POSIX production protections or independently establish seed provenance.

The previous release `45ef79e5e9a876a3b12c15e9a72b7ea5933651c6` passed Actions `37133852203`; its exact SHA/status were reread. That run does not cover this change. Publication must be followed by this commit's exact-SHA full quality workflow; no current full-suite count is asserted here.

## Remaining authority gates

1. New source and exact retained input staging are not deployed or approved by the offline bootstrap. Existing inactive source/runtime/genesis receipts remain historical observations only.
2. No fresh protected real-provider grant exists. One bounded Critic/Creator research cycle requires separate explicit approval for source/input staging, protected grant and secure credential resolution, with one request each, no retries/fallback and retained typed outcomes.
3. Automated protected consumer-pin advancement and an active writer/consumer runtime remain unproven. Synthetic POSIX identity tests and manual pin updates do not establish continuous operation.
4. A rejected baseline cannot be admitted. Future qualification/admission, autonomous paper execution/feedback, service activation and first-live legal/account/capital/reconciliation/kill-switch review remain separate gates. No profitability, testnet/live readiness or whole-project completion is claimed.
