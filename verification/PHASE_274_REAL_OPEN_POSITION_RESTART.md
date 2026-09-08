# Phase 274 — Real Paper Open-Position Restart Verification

**Decision: PASSED — one bounded real paper restart completed with open-position recovery.**

## Scope and safety boundary

- Exactly one restart was issued, only for the existing `autonomous-futures-paper-live.service`.
- Telegram was not restarted. No source deployment, schema repair, state deletion, force-close, artificial tick/trade, tuning, credentials, live/testnet activation, or new scheduler was used.
- The restart was performed with the pinned SSH route `afbot@147.79.18.15`, host `kipopopo`, ED25519 fingerprint `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`, key `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`.
- Remote runtime source remains `/opt/autonomous-futures-bot`; authoritative ledger remains `/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3`.

## Gates immediately before restart

Timestamp: `2026-09-08T04:54:22.686459Z`.

- Paper service: `active/running`, PID `691484`, `NRestarts=0`, `ExecMainStatus=0`.
- Fresh transactional SQLite `mode=ro`, `PRAGMA query_only=1`: integrity `ok`.
- Ledger: `44` opens, `43` closes; exactly one unmatched open and no orphan close.
- Open ID: `paper-cand-09891e9-dogeusdt-20260908044959-0004`.
- Open state: `DOGEUSDT SHORT`, quantity `552.332705`, entry `0.0898220320`, margin `20.0000`, leverage `2.4810785113188349200`.
- Protective state: stop `0.09023881771428571428571428571`, target `0.08898846057142857142857142857`, trailing stop `0.08998785714285714285714285714`, ATR `0.0002778571428571428571428571429`, watermark `0.089710`, state version `1`.
- Candidate/artifact binding: candidate `cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8`, artifact hash `7ab575a56b73520607c68f9e0c183ca86d7f0223472e7299e1bd752eb299d67d`, artifact version `1`, bundle hash `19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816`, strategy DSL version `2`.
- `paper_position_state=1`; `paper_position_update_intent=0`; state matched the unmatched open event exactly.
- Safety: `paper_activation=true` (existing paper contract), `execution_authority=false`, `live_trading_activation=false`, `orders_submitted=0`, `zero_private_credentials=true`, `promotion_state=unpromoted`.
- Health: `RUNNING`, circuit `NORMAL`, reconnects `0`, margin utilization `20.0825%`, cash `99.53284996563182292800`.
- Cash reconciliation included realized close P&L and the one open entry fee: expected `99.53284996563182292800`, exact match.
- The deployed source identity remained the prior verified archive candidate `4b7dd4f30b8e70dea04675b5465695d572c63c33`, manifest `9bf0e048049661c9b57d53a199d96f7e87b8b648b5a991e27fe247e212a0e0bd`. Import resolved from `/opt/autonomous-futures-bot/src/autonomous_futures/paper/live_engine.py`; normalized remote `live_engine.py` SHA-256 matched the candidate file SHA-256 `7a9bdcd1dc0f965254ff66ac80e1bf71db312f7a4a922c066291a64dbc62776f` (remote file was CRLF).

## Backup and restart evidence

- Online SQLite `Connection.backup()` completed before restart, preserving the original runtime database/WAL/SHM.
- Backup handle: `/opt/autonomous-futures-bot/artifacts/paper_live/backups/phase274-pre-restart-20260908T045422Z-paper-ledger.sqlite3`.
- Backup readback: integrity `ok`, `87` events, duplicate open IDs `0`.
- Authorized command executed exactly once: `sudo -n /usr/bin/systemctl restart autonomous-futures-paper-live.service`; return code `0`.
- Shutdown journal showed termination signal, graceful shutdown, exact balance reconciliation with zero drift, `43` closed trades, `1` open position, and `0.01984465836126262400` total open entry fees.

## Recovery and bounded post-restart observation

Timestamp: `2026-09-08T04:55:15Z`, after a bounded 30-second observation.

- Paper service: `active/running`, new PID `693042`, `NRestarts=0`, `ExecMainStatus=0`.
- Telegram remained `active/running`, PID `691490`, `NRestarts=0`.
- Health: `RUNNING`, heartbeat `2026-09-08T04:55:15.331549+00:00`, feed messages `24597`, reconnects `0`, circuit `NORMAL`, margin utilization `20.078%`, cash `99.53284996563182292800`, equity `99.61129888438838292800`.
- Warmup/recovery path was bounded and observable: 100 REST warmup bars were seeded for each monitored symbol; startup completed at `2026-09-08T04:54:45.328176Z`. This is public market-data warmup, not order activity.
- Recovered position matched the exact pre-restart trade ID, side, quantity, entry price, candidate/artifact binding, margin, leverage, and versioned protective/strategy state. `paper_position_update_intent=0`.
- Ledger remained `44` opens / `43` closes / `87` events; integrity `ok`; duplicate opens `0`; no new fees, opens, closes, or orders were observed during the bounded window.
- Protective trailing stop, watermark, and peak P&L advanced after restart. This is normal post-recovery trailing management, not a mismatch: the position remained the same and the state stayed valid.
- The post-restart process resumed feed/management progress, but no close occurred in the observation window. Recovery hydration is directly observed; a later natural close was not claimed.

## Sanitized parent readback

```bash
KH="$LOCALAPPDATA/Temp/afbot-phase274-known_hosts"
ssh-keyscan -T 15 -t ed25519 147.79.18.15 2>/dev/null | ssh-keygen -lf - -E sha256
ssh -i 'C:/Users/thaqi/.ssh/kainode_ed25519_openssh' -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KH" \
  -o HostKeyAlgorithms=ssh-ed25519 -o PubkeyAcceptedKeyTypes=ssh-ed25519 \
  afbot@147.79.18.15 'systemctl show autonomous-futures-paper-live.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus; \
  python3 -c '\''import sqlite3; c=sqlite3.connect("file:/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3?mode=ro",uri=True); c.execute("PRAGMA query_only=ON"); print(c.execute("PRAGMA integrity_check").fetchone()[0]); print(c.execute("select event,count(*) from paper_ledger_events group by event order by event").fetchall()); print(c.execute("select count(*) from paper_position_state").fetchone()[0], c.execute("select count(*) from paper_position_update_intent").fetchone()[0])'\'''
```

## Evidence distinction and final status

- **Observed on VPS:** one controlled restart, graceful shutdown, online backup and backup integrity, new PID/service state, warmup completion, health/feed progress, exact open-position hydration, ledger/cash continuity, no duplicate opens/fees/orders, clean intent table, and ongoing management state.
- **Inherited from prior verified reports:** candidate archive identity and full source manifest hash; offline dual-side recovery rehearsal; prior locked test suite.
- **Not claimed:** natural close during the restart window, live/testnet capability, or promotion readiness.

Final status: **PASS — Phase 274 complete. Stop; no next phase or second restart authorized.**
