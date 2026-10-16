# Production Readiness Gate

**Status: NO-GO for mainnet.** This checklist is tied to the current evidence and
must be refreshed against the exact release, account, and candidate before any
production decision. Passing a development report or running a Testnet service
does not grant live execution authority.

## Current evidence (2026-10-16)

- The Testnet environment-isolation and event-evidence source slice is locally
  committed as `dddfea3cac6d21fe906969d3805545cd5942293a` on
  `codex/ict-lumitraders-experiment`. It has not been pushed, run through
  remote CI, approved as a release, or deployed. Separate ICT research and
  archived diagnostic changes remain uncommitted in the shared checkout and
  are excluded from this source commit.
- `deploy/qualification-admission.json` has `approved_reports: []`, and one
  `approved_portfolio_reports` entry for
  `macro-scalper-uninspected-3sym-medium-frequency-v1`. The portfolio report
  passes all seven portfolio research gates (35 holdout trades, positive
  stressed net PnL, 0.72% drawdown, 3/5 profitable windows, reconciled
  accounting) and says `decision: QUALIFIED`, `execution_authority: false`.
  The active runtime is configured for Testnet and applies additional
  account/domain checks; this receipt does not grant mainnet authority.
- The active portfolio report binds five implementation files. Their SHA-256
  hashes match the local checkout and deployed release:
  `execution/daily_risk.py`, `execution/trade_plan.py`,
  `research/portfolio_qualification.py`,
  `research/runtime_qualification.py`, and
  `strategy/macro_liquidity_scalper.py`.
- Read-only revalidation on 2026-10-16 confirms the admitted portfolio report
  file hash and all five implementation hashes match local bytes. The report's
  Testnet domain is derived from its reconciled
  `authenticated-testnet-equity-scenario-v1` capital scenario; its
  `execution_authority` remains `false`. Of the handoff's six pinned MACRO_SCALPER
  paths, the three present in this checkout have no local changes; the other
  three paths are absent as documented below. The Mainnet admission and signed
  authorization files are absent.
- The holdout ledger at
  `research/qualification-holdout-2026-08-2026-09/holdout-index.json` is
  `partially_consumed` and records this portfolio under
  `consumed_portfolio_validation`. Its BTC context and Aug–Sep 2026 window have
  been used; do not reuse them for retuning or describe them as unconsumed.
- The 2026-06-01 through 2026-08-01 ICT/LumiTraders experiment reports are
  research-only. All eight variants have negative stressed net PnL; no variant
  qualifies for runtime use.
- A read-only systemd query found
  `autonomous-futures-qualified-runtime.service` active since
  `2026-10-15 13:44:32 UTC` (`MainPID=302731`, `NRestarts=0`) with storage under
  `/opt/autonomous-futures-bot/runtime/qualified-testnet`, while
  `autonomous-futures-trader.service` was inactive. The active unit's working
  directory is `/opt/autonomous-futures-bot/releases/qualified-runtime`.
  Its admission-manifest SHA-256 matches the local manifest. The startup
  journal records `ready_to_activate: true` for Testnet preflight, while the
  report still has `execution_authority: false`. A fresh runtime snapshot at
  `2026-10-16 09:15 UTC` records a verified Testnet account reconciliation and
  daily-risk basis, no nonzero positions or open orders, a connected private
  stream with no gap, no cycle/account/scan errors, and a `HEALTHY` watchdog.
  The private stream has received zero events, so order/fill lifecycle remains
  unproven. The local code now adds `exchange-user-events.jsonl` to retain
  normalized user-stream lifecycle events and REST reconciliation checkpoints,
  bound to admission/source hashes and sanitized account/order summaries. The
  read-only `scripts/verify_execution_event_evidence.py` checks the local chain.
  That chain detects edits but is not an exchange signature or an external
  tamper-proof anchor. The active VPS release does not contain this
  instrumentation yet. Do not stop, restart, or replace either writer as part
  of this checklist.
- The checked-in qualified-runtime systemd unit has an `ExecStartPre` that
  invokes `prepare_portfolio_cutover.py --apply-leverage --bootstrap-daily-risk`
  before startup, followed by the runtime preflight. A restart can therefore
  apply leverage settings and bootstrap risk state. Re-read the exact deployed
  unit and rerun read-only account/position/order checks before any approved
  maintenance window; do not treat restart as a telemetry-only change.
- `scripts/run_qualified_runtime.py` now defaults to Testnet and selects only
  credentials for the requested environment. The Mainnet path uses a separate
  admission manifest, requires `testnet: false` receipts, and stores state in
  an external `qualified-mainnet` directory. It remains disabled unless a
  separate authorization document is signed by an offline Ed25519 key whose
  public key is configured outside the repository through
  `AFBOT_MAINNET_AUTHORIZATION_PUBLIC_KEY_FILE`. That authorization expires
  within 30 days. No Mainnet admission, authorization, or public key is stored
  in this checkout, and this change did not read or use Mainnet credentials; it
  does not grant or activate Mainnet execution authority.
- The incoming handoff's six-file pin uses three paths absent from this
  checkout (`strategy/btc_macro_filter.py`, `risk/hawkes_filter.py`, and
  `risk/daily_risk.py`; the current daily-risk module is under `execution/`).
  Do not assume the old paths map one-to-one to the active portfolio's five
  attested files. Reconcile the inventory before qualifying a different
  candidate or release.
- Local verification for the current dirty checkout passed on 2026-10-16:
  111 focused unit tests covering event evidence, runtime/user-stream handling,
  admission and scanning, portfolio execution, order identity, protective
  lifecycle, fill recovery, and Testnet reconciliation; Ruff lint and format,
  Mypy on seven source files, `git diff --check`, and the read-only evidence
  verifier CLI help. These checks use local fixtures/mocks and do not prove
  exchange-confirmed order behavior. The 111-test run preceded the source
  commit; the two bootstrap checks ran against that same source immediately
  before commit. Remote CI and exact-release review remain outstanding.
- The active portfolio resolution and Mainnet manifest/domain checks were
  rerun against the current source on 2026-10-16: 2 focused bootstrap tests
  passed. Runtime activation was not attempted; the Testnet test halts at the
  protected single-writer guard before credentials or network access.
- The source commit above isolates Testnet runtime/evidence changes from the
  remaining ICT research experiment and three archived diagnostic scripts.
  Its changed runtime code is:
  `scripts/run_qualified_runtime.py`,
  `scripts/verify_execution_event_evidence.py`,
  `src/autonomous_futures/execution/causal_scanner.py`,
  `src/autonomous_futures/execution/entry_admission.py`,
  `src/autonomous_futures/execution/portfolio_runtime.py`,
  `src/autonomous_futures/execution/qualification_receipts.py`,
  `src/autonomous_futures/execution/runtime_session.py`, and
  `src/autonomous_futures/execution/execution_event_evidence.py`. The current
  tests in the same commit are `tests/unit/test_causal_scanner.py`,
  `test_entry_admission_time.py`, `test_portfolio_runtime.py`,
  `test_qualified_runtime_bootstrap.py`, `test_runtime_session.py`, and
  `test_execution_event_evidence.py`. The ICT
  experiment (`scripts/qualify_runtime_ict.py`,
  `src/autonomous_futures/research/ict_runtime_qualification.py`, and its
  2026-10-16 artifact directory) is research-only and must not be treated as
  production qualification. The three scripts under `scripts/archive/` are
  retained diagnostics; a hidden-file-aware repository search found no
  remaining references to their old root paths. The source commit is not yet a
  deployable release; a release manifest, exact-source review and remote CI
  remain outstanding.

## Risk limits (keep the metrics distinct)

- Per-trade risk: `0.5%` of actual exchange account equity.
- Daily loss: `5%` of authentic, reconciled equity captured at the UTC day
  boundary. Missing or stale baseline evidence blocks new entries.
- Maximum drawdown: the runtime qualification policy currently defaults to
  `5%`. The ICT experiment explicitly overrode its research gate to `12%`;
  this does not change the runtime policy or daily loss limit.
- The policy specifies no fixed margin, notional, or cash-reserve cap. Exchange
  filters, available margin, stop distance, costs, owned exposure, and remaining
  daily risk still constrain each order.

## Required gates

### 1. Candidate qualification

- Freeze the candidate, parameters, symbol universe, source revision, data and
  funding manifests, fee inputs, and stress assumptions before validation.
- Use an independent holdout whose market data and shared regime context have
  not been consumed by prior candidate selection or tuning. Record any shared
  context consumption in the holdout ledger.
- Meet the checked-in qualification policy: at least 30 OOS trades, positive
  net edge, profit factor at least `1.10`, drawdown within the declared policy,
  at least 3 profitable windows, and positive stressed net PnL. Shared-wallet
  portfolio qualification also requires reconciled wallet/equity accounting.
- Requalify for the intended Mainnet account domain with its actual capital,
  commission rates, filters, and allowed leverage. A Testnet-bound portfolio
  receipt cannot be reused as Mainnet qualification.
- Preserve a rejected verdict. A `decision: QUALIFIED` research report alone
  does not grant Mainnet execution authority.

### 2. Source and admission integrity

- Review and commit the intended source changes on a named branch; verify the
  active portfolio's five source hashes again at release time. Reconcile the
  older handoff pin paths listed above instead of assuming renamed files are
  byte-identical.
- Bind the final qualification receipt to the exact source/data/policy hashes
  used by the release.
- Confirm the admission manifest grants authority only to that exact candidate
  and portfolio. Unknown, missing, stale, or mismatched evidence must fail
  closed.

### 3. Testnet runtime proof

- Reconcile the active Testnet unit's loaded release, admission result,
  account-evidence freshness, and writer ownership using read-only checks before
  any operational change.
- Demonstrate order lifecycle behavior using existing exchange-confirmed
  evidence or an isolated test harness: accepted and rejected submissions,
  partial fills, cancellations, ambiguous timeouts, recovery, protective
  reduce-only orders, and final position/order reconciliation. Do not force a
  restart of the active Testnet writer or start a second writer with its key.
- Demonstrate private-stream renewal, reconnect and REST reconciliation, stale
  data entry vetoes, clock/rate-limit error handling, watchdog alerts, and a
  tested operator shutdown/rollback procedure in the approved Testnet scope.
- Agree the soak duration and numeric acceptance criteria before starting the
  measurement period. Report unresolved mismatches, missing telemetry, and
  exchange-confirmed results separately.

### 4. Mainnet security and controlled rollout

- Audit the actual production API key permissions and source-IP restrictions;
  verify withdrawals are disabled and secrets are not stored in source, logs,
  or artifacts.
- Confirm account mode, leverage, symbol filters, margin availability, fees,
  funding, and actual UTC day-start equity on the production account before
  sizing any order.
- Implement a separate Mainnet configuration that is explicit and disabled by
  default. It must require a Mainnet-bound admission receipt and reject
  Testnet credentials, Testnet receipts, or ambiguous environment selection.
- Keep the offline Mainnet authorization signing key outside the server and
  repository. Install only its trusted Ed25519 public key outside the release
  tree; require the signed authorization to bind exact report and selection
  hashes, and expire within 30 days.
- Prepare a reviewed release, deployment manifest, rollback version, alerts,
  and a deliberately small initial allocation. Do not scale until the initial
  observation period meets its predeclared criteria.
- Mainnet deployment, credential changes, service handoff, and exchange orders
  require a separate explicit go/no-go decision after every preceding gate is
  evidenced. This checklist itself grants none of those permissions.

## Immediate next engineering action

The source slice is frozen at commit
`dddfea3cac6d21fe906969d3805545cd5942293a`. A draft manifest bound to that
commit is recorded at
[`deploy/release-manifests/qualified-testnet-event-evidence-20261016.json`](../deploy/release-manifests/qualified-testnet-event-evidence-20261016.json)
with status `SOURCE_COMMIT_REVIEW_REQUIRED`. Next, complete exact-source review
and remote CI. Only then can an explicitly approved maintenance window be
planned for the protected Testnet runtime. Do not bypass the single-writer
guard or start another writer with the shared key. After an approved
deployment, passively collect real Testnet user-stream events and REST
reconciliation checkpoints, then verify the resulting journal with:

```powershell
uv run --locked python scripts/verify_execution_event_evidence.py <ledger>
```

The active snapshot has zero user-data events, so live exchange evidence
remains missing. The local hash chain detects edits but is not an exchange
signature or externally anchored tamper-proof evidence. Do not create orders
for this collection step.
