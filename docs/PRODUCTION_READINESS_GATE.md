# Production Readiness Gate

**Status: NO-GO for mainnet.** This checklist is tied to the current evidence and
must be refreshed against the exact release, account, and candidate before any
production decision. Passing a development report or running a Testnet service
does not grant live execution authority.

## Current evidence (2026-10-16)

- The Testnet environment-isolation and event-evidence source slice is
  `dddfea3cac6d21fe906969d3805545cd5942293a` and is on open draft PR #1.
  Remote CI run `38921855487` passed on PR head
  `b8c596a7cebc2af6f4baf3561bc7641d22b0335e`; run `38924314821` passed on
  exact PR head `2e9c28475ae99aa57c276888e29d0921dc301ede` with 6,036 tests
  passed, one Windows-only test skipped on Linux, and two warnings. Runs
  `38888385968` and `38887005557` also passed on earlier heads. PR #1 remains
  draft; the exact source is deployed to Testnet under the user's direct
  authorization for controlled maintenance and normal Testnet order flow.
  Mainnet is not authorized. Follow-up commits
  stabilize the scanner telemetry fixture and satisfy repository-wide lint
  and formatting checks. Separate ICT research and archived diagnostic
  changes remain outside the PR.
- `deploy/qualification-admission.json` has `approved_reports: []`, and one
  `approved_portfolio_reports` entry for
  `macro-scalper-uninspected-3sym-medium-frequency-v1` covering AVAXUSDT,
  ETHUSDT, and SOLUSDT. The portfolio report
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
  tamper-proof anchor. The 09:15 snapshot predates deployment and did not
  contain this instrumentation; the controlled cutover below now runs the
  event-evidence release. The historical snapshot does not prove live order
  lifecycle behavior.
- A fresh read-only check at approximately `2026-10-16 15:06 UTC` confirms the
  qualified Testnet service remains active as `MainPID=302731`,
  `NRestarts=0`; the watchdog timer is waiting, and the watchdog API reports
  `HEALTHY` with no critical or warning alerts. The authenticated REST account
  snapshot was 16.1 seconds old, reconciled with zero wallet/equity drift, and
  had a verified daily-risk basis, no nonzero positions, and zero open orders.
  The private stream was connected and reconciled but still had zero events;
  `exchange-user-events.jsonl` is absent and the active release has neither the
  event-evidence module nor its verifier. These are point-in-time observations,
  not proof of lifecycle behavior.
- The incoming pasted handoff identifies an ETH/LINK/AVAX portfolio as active.
  The running unit, deployed admission manifest, and runtime scanner state
  instead agree on `macro-scalper-uninspected-3sym-medium-frequency-v1`
  (AVAX/ETH/SOL). The deployed manifest SHA-256 is
  `4b4a0d8809a99cfcb1b15f3a3b96e71fd1511a2186edc5c6f8a2a46484a4d913`; its
  holdout report and all five implementation hashes match the deployed
  release. The user confirmed this deployed AVAX/ETH/SOL candidate as the
  target for future qualification and deployment work. That selection alone
  did not authorize changes; the user later explicitly authorized one
  controlled Testnet cutover and normal Testnet order flow on 2026-10-16.
  Treat the older ETH/LINK/AVAX handoff designation as superseded for this
  work. Mainnet remains unauthorized.
- The checked-in qualified-runtime systemd unit has an `ExecStartPre` that
  invokes `prepare_portfolio_cutover.py --apply-leverage --bootstrap-daily-risk`
  before startup, followed by the runtime preflight. A restart can therefore
  apply leverage settings and bootstrap risk state. Re-read the exact deployed
  unit and rerun read-only account/position/order checks before any approved
  maintenance window; do not treat restart as a telemetry-only change.
- Before the 2026-10-16 cutover, read-only inspection confirmed this was a user-level
  systemd unit with `Restart=on-failure`. Its configured working directory is
  the symlink `/opt/autonomous-futures-bot/releases/qualified-runtime`, which
  resolved to `/opt/autonomous-futures-bot/.release-web-20261014`;
  the account and event-evidence files are under the separate
  `/opt/autonomous-futures-bot/runtime/qualified-testnet` directory. A
  controlled rollout can preserve that exact release directory as the rollback
  target and switch the symlink atomically. Unexpected startup failure can
  automatically rerun the side-effectful `ExecStartPre`; the deployment plan
  therefore calls for a temporary one-attempt restart policy during an
  approved maintenance window.
- A fresh read-only staged-candidate check at approximately
  `2026-10-16 15:41 UTC` returned `ready_to_activate: true`, no blocking
  reasons, and preflight hash
  `864984af306600e607396b613874c3983cf92414942ad02ec84d39fb91877cd9`.
  The active unit remained PID `302731` with `NRestarts=0` and
  `Restart=on-failure`; the release symlink still resolved to
  `.release-web-20261014`. The authenticated Testnet snapshot was fresh and
  reconciled, the watchdog was `HEALTHY`, there were zero nonzero positions
  and open orders, and the legacy writer remained disabled and inactive. The
  staged release is at
  `/opt/autonomous-futures-bot/.release-qualified-testnet-event-evidence-20261016-dddfea3`;
  its archive SHA-256 is
  `27fa311b2f2ed98d8ee5da5a37bfbb4c156b86a8f2dec5ee6166c0af01f8e5d4`.
  These are point-in-time checks; refresh them immediately before cutover.
- The controlled Testnet cutover completed at `2026-10-16 15:54:32 UTC`.
  The release symlink now resolves to
  `.release-qualified-testnet-event-evidence-20261016-dddfea3`; the previous
  `.release-web-20261014` directory is preserved as the rollback target. The
  new unit started once as PID `381572` with `NRestarts=0` and temporary
  `Restart=no`. Startup preparation kept AVAX/ETH/SOL at 1x, verified daily
  risk and the execution domain, and did not re-bootstrap the current daily
  risk baseline. The new account snapshot reconciles with zero wallet/equity
  drift, no positions, and no open orders. The private stream is connected
  with no gap but has received zero user-data events; the event ledger verifies
  with two REST reconciliation records. The initial watchdog check was
  `WARNING` while the restarted Hawkes model collected 390 arrivals for each
  of 12 dimensions; the warning later cleared after warmup.
- At `2026-10-16T16:04:58Z`, the watchdog was `HEALTHY`, the maintenance alert
  state had cleared, and the account snapshot was 8.1 seconds old with zero
  positions and orders. Market and private streams were connected, with no
  private-stream gap or reconciliation requirement. The event ledger verified
  with two REST reconciliation records and zero user-data events. The original
  `Restart=on-failure` policy was restored with `NRestarts=0`; the 14-day soak
  began at this checkpoint and must run no earlier than
  `2026-10-30T16:04:58Z`. Mainnet remains NO-GO.
- The next read-only checkpoint at `2026-10-16T16:09:44Z` found the unit active
  as PID `381572` (`NRestarts=0`, `Restart=on-failure`), watchdog `HEALTHY`
  without active alerts, verified account reconciliation 16.6 seconds old,
  verified daily risk, zero positions and orders, and stable Hawkes state. The
  scanner had zero ready variants in a sideways BTC regime. The ledger verifier
  passed with two REST reconciliation records and zero user-data records. This
  does not satisfy the soak's per-symbol completed-lifecycle requirement.
- A read-only Mainnet code-path audit at `2026-10-16T16:12Z` confirmed that
  `scripts/run_qualified_runtime.py` defaults to Testnet; Mainnet uses a
  separate admission manifest, credentials, execution-domain check, and
  `qualified-mainnet` storage outside the repository. The Mainnet path requires
  an offline Ed25519 authorization verified with a public key configured
  outside the repository, binds the selected report and selection hashes, and
  rejects authorization older than 30 days. Admission and signed authorization
  are checked before Mainnet credentials are read or a writer lease is acquired.
  Existing CI coverage includes missing-admission, environment-domain,
  isolated-storage, and authorization-hash checks. The reviewed runtime,
  receipt verifier, and bootstrap-test file hashes match the release manifest
  and remain unchanged since the deployed source revision. This source review
  does not verify a production account or its API-key permissions: the Mainnet
  admission and authorization files are absent from this checkout, and the
  local shell has no Mainnet authorization public-key path configured.
- A fresh runtime check at approximately `2026-10-16T16:15:46Z` still found
  the qualified unit active (`PID 381572`, zero restarts), watchdog healthy,
  verified daily risk, fresh account reconciliation, and no positions or open
  orders. The scanner evaluated all six portfolio variants and reported
  `signal_ready=false` for each: BTC regime was sideways, macro alignment was
  false, and relative volume did not meet any candidate threshold. Hawkes was
  stable, and the service journal had no warning-or-higher entries since soak
  start. A read-only ledger verification in the same checkpoint window passed
  with two REST reconciliation records and zero user-data records.
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
  before commit.
- GitHub Actions run `38921855487` passed on PR head
  `b8c596a7cebc2af6f4baf3561bc7641d22b0335e`: 6,036 Python tests passed and
  one Windows NTFS locking test was skipped on Linux; frontend tests/build,
  repository-wide Ruff lint/format, strict Mypy, Python compileall, and
  GitGuardian all passed. The exact `dddfea3` source diff and all 14
  manifest-listed file hashes were reviewed against both the frozen commit
  and current checkout; no blocking source issue was identified. CI verifies
  code behavior and static checks, not exchange-confirmed order behavior.
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
  remaining references to their old root paths. The exact source commit is
  deployed on Testnet. The release manifest records the user's approval and
  deployment state. The user confirmed the deployed AVAX/ETH/SOL candidate as
  the target for future work.

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
- Use the predeclared 14-calendar-day Testnet soak and numeric criteria in
  `deploy/TESTNET_EVENT_EVIDENCE_ROLLOUT.md`. Extend the soak if an
  exchange-confirmed completed lifecycle has not been observed on every
  candidate symbol. Report unresolved mismatches, missing telemetry, and
  exchange-confirmed results separately.
- The event-evidence verifier proves hash-chain integrity, not lifecycle
  completion. At soak review, reconstruct each symbol's entry and exchange-
  confirmed exit fills from authenticated order updates, then bind them to a
  later successful REST reconciliation with no remaining position, open order,
  or unresolved lifecycle. Preserve the event sequence and reconciliation
  checkpoint used for each symbol's count.

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

The release source slice is frozen at commit
`dddfea3cac6d21fe906969d3805545cd5942293a`. Exact-source review is complete
with no blocking finding; all 14 included files match the commit and release
manifest. CI run `38924314821` passed on PR head
`2e9c28475ae99aa57c276888e29d0921dc301ede` in draft PR #1. The release
manifest is recorded at
[`deploy/release-manifests/qualified-testnet-event-evidence-20261016.json`](../deploy/release-manifests/qualified-testnet-event-evidence-20261016.json)
with status `TESTNET_SOAK_IN_PROGRESS`; deployment is recorded true. The user
authorized one controlled Testnet cutover for the AVAX/ETH/SOL portfolio,
including normal Testnet order flow, and the cutover succeeded. The controlled
maintenance and rollback procedure is documented at
[`deploy/TESTNET_EVENT_EVIDENCE_ROLLOUT.md`](../deploy/TESTNET_EVENT_EVIDENCE_ROLLOUT.md).
Continue the 14-day Testnet soak and collect genuine user-stream events and
REST reconciliation checkpoints. Do not bypass the single-writer guard or
start another writer with the shared key. Verify the resulting journal with:

```powershell
uv run --locked python scripts/verify_execution_event_evidence.py <ledger>
```

The active snapshot has zero user-data events, so live exchange evidence
remains missing. The local hash chain detects edits but is not an exchange
signature or externally anchored tamper-proof evidence. Do not create orders
for this collection step.
