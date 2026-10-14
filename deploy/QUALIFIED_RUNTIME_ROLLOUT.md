# Qualified runtime rollout — blocked under current operator constraints

**Current transfer:** 14 October 2026. See `ANTIGRAVITY_HANDOFF_2026-10-14.md` and canonical
`CODEX_HANDOFF.md`. The operator protects the active legacy daemon/PID 87549 and selected
reuse of its existing Testnet key. The replacement guard requires legacy inactivity. Those
conditions cannot currently coexist, so this document is a prerequisite/reference plan,
not an executable activation procedure or permission to change the protected service.

The separate runtime service is prepared locally and has not been installed or started.
`autonomous-futures-trader.service` and PID 87549 must remain untouched throughout rollout.
The new service has its own name, release directory and durable state directory.

Before installing the unit, all of the following must have actual supporting evidence:

- Genuine canonical strategy and portfolio qualification under the selected capital policy,
  with complete source-file provenance, current implementation bindings and passing gates.
  Completed rejected reports must remain rejected. The admission manifest is currently empty.
- Exact accepted report byte hashes and repository-relative report paths in
  `deploy/qualification-admission.json`, reviewed with the qualification evidence.
- The operator selected actual exchange ACCOUNT equity for the 5% daily-loss budget.
  The secure VPS environment file now specifies AFBOT_EQUITY_BASIS=ACCOUNT.
- The operator selected reuse of the existing Testnet API key. The qualified bootstrap now
  uses the existing `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET_KEY` pair. Its
  fail-closed handoff guard requires the legacy unit to be disabled, configured with
  `Restart=no`, and fully inactive (`ActiveState=inactive`, `SubState=dead`, `MainPID=0`)
  before startup and again at the final entry boundary. Do not start the qualified service
  while the protected legacy daemon may still write with the shared key. The OS lease cannot
  fence PID 87549, and no VPS handoff has been performed.
- Authentic day-start equity captured at the UTC boundary and reconciled account/owned fills.
  Missing baselines disable entries; they must never be replaced with a mid-day balance.
- Real feed warmup, fresh clock/trade/depth observations, a measured rho below one from
  an identified fit (no fitted baseline at the optimizer's lower bound), and
  exchange-confirmed reduce-only prearmed coverage before any opening order.
- The service's required `--hawkes-calibration` argument points to
  `artifacts/qualification/runtime-microstructure/runtime-hawkes-calibration-20261013.json`.
  Startup verifies the calibration artifact, its selection and independent-validation
  profile hashes, the fitted implementation hash, and matching 12-pair trace evidence.
  This artifact supplies only beta=7.5/s to the estimator; it explicitly grants neither
  strategy qualification nor execution authority.

The new environment file must be owned by afbot and readable only by that user (mode 0600).
It supplies AFBOT_EQUITY_BASIS plus the existing Testnet values as
BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET_KEY. Reuse the credentials already
configured for the legacy service; do not create a second trading key. Copy credentials
securely without printing them, and never put their values in Git, reports or chat.

The release link `/opt/autonomous-futures-bot/releases/qualified-runtime` must point to a
verified complete release. Durable state and the account lease live outside that release,
at `/opt/autonomous-futures-bot/runtime/qualified-testnet`. Never discard them on an upgrade.
Installing this unit does not authorize bypassing its runtime qualification checks.

Do not enable/start the new writer under the current protected-daemon constraint. Even if
economic and account prerequisites later pass, an explicit reconciled operator decision
is still required to resolve the same-key writer transition; qualification alone cannot
authorize stopping or reconfiguring PID 87549. Until that decision, read-only preflights
must confirm the protected unit is untouched, and independent offline work can continue.
After a separately authorized transition, verify the actual writer exclusivity, process,
account observations, owned-order reconciliation, protective coverage and runtime health.
Service startup, unit-file validation and green unit tests alone do not prove activation.

The basis-only environment file currently contains no credentials. Credential setup remains
incomplete. The bootstrap and final entry guard now support the selected same key, but both
remain blocked until a read-only systemd check proves that the legacy unit is disabled,
configured not to restart, and fully inactive. Do not alter the running service, remove its
API permissions, or stop, restart, kill, or signal PID 87549. Do not paste secrets into chat.

To run a non-mutating, read-only preflight check of the admission manifest, Hawkes calibration
artifact, `ACCOUNT` `0.5%` / `5%` risk policy, 12-pair universe, and optional systemd handoff
guard or durable `trade-autopsies.json` state, execute:

```bash
python scripts/preflight_qualified_runtime.py --allow-blocked
```
