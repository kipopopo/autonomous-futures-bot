# Qualified runtime rollout — historical single-writer portfolio cutover record

**Historical snapshot (15 October 2026; superseded for current readiness by
[`docs/PRODUCTION_READINESS_GATE.md`](../docs/PRODUCTION_READINESS_GATE.md)):** Following explicit operator authorization, the legacy
daemon (`autonomous-futures-trader.service`) was reconfigured to `Restart=no`, disabled, and
stopped cleanly (`ActiveState=inactive`, `SubState=dead`, `MainPID=0`). All 6 preflight gates
passed (`ready_to_activate: true`, `blocking_reasons: []`, `preflight_hash: 9e62c8aaf3f9...`),
and `autonomous-futures-qualified-runtime.service` (`MainPID=63408`, `NRestarts=0`) is now the
sole active Testnet writer running `PortfolioCausalScanner` (`macro-scalper-uninspected-3sym-medium-frequency-v1`).

## Verified Prerequisites (All Passing Except Single-Writer Handoff)

All technical, mathematical, and exchange-domain prerequisites are now verified (`passed: true`):

- **Portfolio Qualification & Admission (`deploy/qualification-admission.json`)**:
  - Admitted portfolio ID: `macro-scalper-uninspected-3sym-medium-frequency-v1` (`AVAXUSDT`, `ETHUSDT`, `SOLUSDT`, 6 uncorrelated members across 3 symbols, `leverage = 1x`).
  - Artifact: `artifacts/qualification/portfolio-scalper-mf-holdout-2026-08-2026-09/portfolio-72de22bde9a30101.json` (`sha256: 72de22bde9a30101c791bcc981c89481c176b6a4fd63acfd4e2495e8e9122d89`).
  - Qualified with `passed: true`, `expected_return_lcb_bps: +1.1066335601381197`, `profit_factor: 1.5476572638478152`, `max_drawdown_pct: 0.09547914438252931%`, `max_pairwise_return_correlation: 0.09335647615229111`.
- **Capital Policy & Authentic UTC Day-Start Equity (`AFBOT_EQUITY_BASIS=ACCOUNT`)**:
  - `0.5%` per-trade risk (`0.005`) and `5%` daily loss budget (`0.05`) on actual exchange `ACCOUNT` equity.
  - Pre-cutover preparation (`scripts/prepare_portfolio_cutover.py --apply-leverage --bootstrap-daily-risk`) normalized `AVAXUSDT`, `ETHUSDT`, and `SOLUSDT` leverage to `1x` on a flat account (`0` open positions, `0` open orders) and initialized `daily-risk.json` + `exchange-account.json`.
- **Measured Hawkes Calibration (`--hawkes-calibration`)**:
  - Points to `artifacts/qualification/runtime-microstructure/runtime-hawkes-calibration-20261013.json` (`beta = 7.5/s`, `all_12_pairs_passed: true`).
- **Single-Writer Handoff Guard (`systemd_legacy_handoff`)**:
  - Reuses the existing `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET_KEY` from `/opt/autonomous-futures-bot/.env` alongside `/opt/autonomous-futures-bot/.env.qualified-runtime` (`mode 0600`).
  - Both `ExecStartPre` (`prepare_portfolio_cutover.py --require-legacy-inactive` and `preflight_qualified_runtime.py --check-systemd`) and `ExecStart` (`run_qualified_runtime.py`) fail closed unless `autonomous-futures-trader.service` has `UnitFileState=disabled`, `Restart=no`, `ActiveState=inactive`, `SubState=dead`, and `MainPID=0`.

## Read-Only Preflight Verification (Safe While Legacy Writer Is Running)

To verify all 6 preflight gates without mutating the running legacy service:

```bash
/opt/autonomous-futures-bot/.venv/bin/python \
  /opt/autonomous-futures-bot/releases/qualified-runtime/scripts/preflight_qualified_runtime.py \
  --repo /opt/autonomous-futures-bot/releases/qualified-runtime \
  --storage-dir /opt/autonomous-futures-bot/runtime/qualified-testnet \
  --account-path /opt/autonomous-futures-bot/runtime/qualified-testnet/exchange-account.json \
  --equity-basis ACCOUNT \
  --check-systemd \
  --allow-blocked
```

While `autonomous-futures-trader.service` is active, this command exits `0` with:
- `capital_policy.passed = true`
- `hawkes_calibration.passed = true`
- `qualification_admission.passed = true` (`admission_mode = "portfolio"`)
- `account_and_portfolio_domain.passed = true`
- `storage_dir.passed = true`
- `systemd_legacy_handoff.passed = false` (`legacy_writer_still_active_or_enabled`)

## Operator-Authorized Controlled Cutover Procedure (DO NOT RUN WITHOUT EXPLICIT CONSENT)

Only after the operator explicitly authorizes stopping the legacy service (`autonomous-futures-trader.service`):

1. **Reconfigure `autonomous-futures-trader.service` to `Restart=no`, disable, and stop cleanly**:
   ```bash
   mkdir -p ~/.config/systemd/user/autonomous-futures-trader.service.d
   printf "[Service]\nRestart=no\n" > ~/.config/systemd/user/autonomous-futures-trader.service.d/cutover-no-restart.conf
   systemctl --user daemon-reload
   systemctl --user disable --now autonomous-futures-trader.service
   systemctl --user show autonomous-futures-trader.service -p ActiveState -p SubState -p MainPID -p UnitFileState -p Restart
   ```
2. **Verify all 6 preflight gates pass (`overall_ready_for_activation: true`, exit code `0` without `--allow-blocked`)**:
   ```bash
   /opt/autonomous-futures-bot/.venv/bin/python \
     /opt/autonomous-futures-bot/releases/qualified-runtime/scripts/preflight_qualified_runtime.py \
     --repo /opt/autonomous-futures-bot/releases/qualified-runtime \
     --storage-dir /opt/autonomous-futures-bot/runtime/qualified-testnet \
     --account-path /opt/autonomous-futures-bot/runtime/qualified-testnet/exchange-account.json \
     --equity-basis ACCOUNT \
     --check-systemd
   ```
3. **Enable and start `autonomous-futures-qualified-runtime.service`**:
   ```bash
   systemctl --user enable --now autonomous-futures-qualified-runtime.service
   systemctl --user status autonomous-futures-qualified-runtime.service --no-pager
   ```

## Controlled Rollback Procedure

If rollback to `autonomous-futures-trader.service` is required:

```bash
systemctl --user disable --now autonomous-futures-qualified-runtime.service
rm -f ~/.config/systemd/user/autonomous-futures-trader.service.d/cutover-no-restart.conf
systemctl --user daemon-reload
systemctl --user enable --now autonomous-futures-trader.service
```
