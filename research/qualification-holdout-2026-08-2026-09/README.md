# Partially consumed qualification holdout

Contains checksum-verified Binance USD-M monthly 1-minute kline and funding-rate archives for all 12 active pairs, covering August and September 2026. Archive bytes were validated against Binance-published checksums and indexed in `holdout-index.json`.

Three frozen Macro Scalper candidates have been evaluated on 2026-08-01 through 2026-10-01:
- `LINKUSDT` (`macro-scalper-linkusdt-d-3.5-t2.5`): rejected with one trade (`artifacts/qualification/runtime-scalper-link-holdout-2026-08-2026-09/LINKUSDT-d03d7df747e61edd.json`; stale source hashes, diagnostic only).
- `XRPUSDT` (`macro-scalper-xrpusdt-d-4.0-t3.0`): bridged from `scalper-symmetric-short-selected-candidates-v3.json` to `frozen-xrp-symmetric-short-candidate-v1.json` and rejected with zero filled trades (`1` signal, `1` unfilled maker entry; `artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json`), with explicit disclosure that `BTCUSDT 1h` shared regime context was previously consumed by the `LINKUSDT` diagnostic while the target `XRPUSDT` partition was uninspected before freeze.
- `SUIUSDT` (`macro-scalper-suiusdt-d-3.4-t4.5`): frozen in `frozen-sui-symmetric-short-candidate-v1.json` prior to building the `SUIUSDT` `2026-08..2026-09` extension cache; achieved positive net edge (`+6.6411 USDT`, `profit_factor=true`, `drawdown=true`) across `6` filled trades on the 2-month holdout (`artifacts/qualification/runtime-scalper-sui-holdout-2026-08-2026-09/SUIUSDT-3072a78e72c0be73.json`; shared-wallet portfolio `XRPUSDT + SUIUSDT` achieved `+6.3503 USDT`, `1.405%` drawdown in `artifacts/qualification/portfolio-scalper-holdout-2026-08-2026-09/portfolio-1c0ce7320bb8600d.json`), and was formally rejected on the 30-trade minimum OOS sample and 2x fee/slippage stress gates (`execution_authority=false`).

The holdout was not used for parameter tuning, but it is no longer globally untouched: mark `LINKUSDT`, `XRPUSDT`, `SUIUSDT`, and `BTCUSDT` regime-context observations for this interval as consumed.

The target-pair observations for ETHUSDT, SOLUSDT, DOGEUSDT, BNBUSDT, AVAXUSDT, NEARUSDT, APTUSDT, and ADAUSDT remain uninspected. Keep those partitions reserved until candidate source, policy, and parameters are frozen. The archive index grants no qualification or execution authority.
