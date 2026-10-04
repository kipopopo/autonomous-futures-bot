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

## Publication and approved-cycle preflight follow-up

Release `9944c9be90f5b17bc26cae500e81a20ddd8adacf` passed exact-head Actions [37210559196](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/37210559196), quality job `111460707073`. Log readback reports **5,000 passed, 1 skipped, 2 warnings in 915.96s**; the skip is the Windows NTFS file-locking case on Linux. Warnings concern Starlette TestClient/httpx deprecation and malformed-date fixture parsing. Lint, format, types and compilation succeeded. Local HEAD matched remote main and was clean at `2026-10-04T23:03:50+08:00`. The durable local `publication-verification.json` records that observation.

The owner subsequently selected **“Lulus pakej satu kitaran research-only ini”**: protected staging of exactly that SHA and verified seed/cache copies; a protected permit; at most one Critic plus one Creator request using Google AI Studio `gemma-4-31b-it`; existing credentials through safe resolution; valid fresh-epoch acceptance and protected pin advancement; one OOS evaluation and retained honest outcome. No retry, fallback, tuning, historical changes, service restart/activation, paper admission, testnet/live or orders. Failure of access or prerequisites stops the run.

Before any remote action, source preflight identified a credential-delivery mismatch: the existing staging service uses `LoadCredentialEncrypted` / `CREDENTIALS_DIRECTORY`, while the cycle's shared provider resolver only checked environment and repository `.env`. The approved real run remains held, with **zero SSH attempts, real credential reads, provider requests, remote writes or epoch acceptances** during this follow-up. Six synthetic RED cases demonstrated ignored configured runtime credentials / unsafe environment fallback. The offline repair reuses `resolve_staging_credential` without environment fallback for an explicit absolute runtime directory, maps errors to a sanitized `MissingCredentialsError`, and preserves the previous env/.env cascade only when no runtime directory is configured. No encrypted source is read or decrypted by these tests.

GREEN: 11 credential-resolution cases passed; six-module affected regression **142 passed in 116.69s**, including the actual synthetic runtime-file reader after the permit budget reservation. Workflow-scoped Ruff/format, native/Linux mypy, lock/diff passed. The initial format check requested Python 3.14 exception syntax formatting; the corrected check passed without behavioral changes. The new source needs its own exact-SHA CI and an explicitly updated staging pin; approval of `9944c9b` is not approval to deploy a different commit.

## Remaining authority gates

1. Source and exact retained inputs are not deployed. Staging approval above pins `9944c9b`; it must be updated before staging the repaired source. Existing inactive source/runtime/genesis receipts remain historical observations only.
2. The bounded cycle package is approved but held on its prerequisite; no protected real-provider grant has been installed or consumed. Resume only after the repaired source's quality gate and exact staging-pin approval, with the same two-request budget and all original limits intact.
3. Automated protected consumer-pin advancement and an active writer/consumer runtime remain unproven. Synthetic POSIX identity tests and manual pin updates do not establish continuous operation.
4. A rejected baseline cannot be admitted. Future qualification/admission, autonomous paper execution/feedback, service activation and first-live legal/account/capital/reconciliation/kill-switch review remain separate gates. No profitability, testnet/live readiness or whole-project completion is claimed.
