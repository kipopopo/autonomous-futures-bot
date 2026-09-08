# Phase 275 — Recovered Position Natural-Close Observation

**Outcome: STILL OPEN — bounded observation ended without a natural close.**

## Scope and safety

Read-only follow-through only. No restart, forced close, trade, strategy change, repair, scheduler, credential access, or VPS write was performed. SSH was pinned to `afbot@147.79.18.15`, ED25519 `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`, key `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`. The local repository was clean at parent commit `5752a3fef94cb09b0b87245447591ffdfa8f925f` before this report.

## Evidence

Remote observations used fresh transactional SQLite read-only connections with `PRAGMA query_only=1`; integrity was `ok`. The authoritative ledger was `/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3`.

- First snapshot: `2026-09-08T05:01:31.402389Z`.
- One finite recheck after 10 seconds: `2026-09-08T05:02:03.956627Z`.
- Target `paper-cand-09891e9-dogeusdt-20260908044959-0004` has exactly one event: sequence `86`, one `open`, `DOGEUSDT SHORT`, quantity `552.332705`, fill `0.0898220320`, occurred `2026-09-08T04:49:59Z`, entry fee `0.01984465836126262400`.
- No target close was observed; therefore no target exit fee or target net P&L exists yet. The target position state remains present at version `1`; the target dirty-intent query is empty. State is therefore not retired because the position remains open.
- Ledger totals at both snapshots: `45` opens, `43` closes; two unmatched opens are the target and newer `paper-cand-009ebbf-solusdt-20260908045959-0001`. Duplicate open IDs and orphan closes were empty. Global totals are context only and are not identity proof.
- Decimal reconciliation at the recheck: closed net P&L `-0.44730537600691444800`; unmatched entry fees target `0.01984465836126262400` plus newer SOL `0.015371467027612800`, total `0.03521612538887542400`; `100.00 - 0.44730537600691444800 - 0.03521612538887542400 = 99.51747849860421012800`, exactly matching reported cash `99.51747849860421012800`.
- Health/service recheck: paper service `active/running`, PID `693042`, `NRestarts=0`, `ExecMainStatus=0`; Telegram `active/running`, PID `691490`, `NRestarts=0`, `ExecMainStatus=0`. Health was `RUNNING`, circuit `NORMAL`, feed reconnects `0`, feed messages advanced from `255152` to `281684`, `orders_submitted=0`, `execution_authority=false`, `live_trading_activation=false`, `zero_private_credentials=true`.
- Telegram checkpoint at `2026-09-08T05:00:03.324440Z` had `last_sequence=88`; ledger's latest sequence was also `88`. This shows checkpoint progress through the currently observed ledger sequence, not Telegram delivery confirmation. No target close sequence existed to verify.
- Health and checkpoint files are point-in-time snapshots: the second health heartbeat was `2026-09-08T05:01:37.435943Z`, earlier than the `05:02:03.956627Z` ledger recheck; no claim is made that every file was sampled atomically.

## Safe parent readback

```bash
KH="$LOCALAPPDATA/Temp/afbot-phase275-known_hosts"
ssh-keyscan -T 15 -t ed25519 147.79.18.15 2>/dev/null | ssh-keygen -lf - -E sha256
ssh -i 'C:/Users/thaqi/.ssh/kainode_ed25519_openssh' -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KH" \
  -o HostKeyAlgorithms=ssh-ed25519 -o PubkeyAcceptedKeyTypes=ssh-ed25519 \
  afbot@147.79.18.15 'systemctl show autonomous-futures-paper-live.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus; \
  python3 -c '\''import sqlite3; c=sqlite3.connect("file:/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3?mode=ro",uri=True); c.execute("PRAGMA query_only=ON"); print(c.execute("PRAGMA integrity_check").fetchone()[0]); print(c.execute("select sequence,event,trade_id,entry_fee,exit_fee,net_pnl from paper_ledger_events where trade_id=\"paper-cand-09891e9-dogeusdt-20260908044959-0004\" order by sequence").fetchall())'\'''
```

**Final status:** target remained open after the one permitted finite recheck. No further observation, restart, or live authority is authorized by this report.
