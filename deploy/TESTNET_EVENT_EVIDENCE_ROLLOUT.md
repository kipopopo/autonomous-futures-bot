# Controlled Testnet event-evidence rollout

**Status: TESTNET SOAK IN PROGRESS, started 2026-10-16 16:04:58 UTC.** This
plan is limited to Testnet and the already deployed portfolio. It is not a
Mainnet release plan.

## Release identity and scope

- Candidate: `macro-scalper-uninspected-3sym-medium-frequency-v1`
  (`AVAXUSDT`, `ETHUSDT`, `SOLUSDT`). The user confirmed this candidate as the
  target for future qualification and deployment work.
- Source: `dddfea3cac6d21fe906969d3805545cd5942293a`.
- The user explicitly authorized one controlled Testnet deployment window
  for this source and candidate, including normal scanner behavior and
  Testnet order submission when the strategy signals. This approval was
  recorded in the Codex task on 2026-10-16. It does not authorize Mainnet.
- Release manifest:
  [`release-manifests/qualified-testnet-event-evidence-20261016.json`](release-manifests/qualified-testnet-event-evidence-20261016.json).
- The manifest records Testnet deployment approval and the successful
  controlled cutover. The new runtime is active with its original
  `Restart=on-failure` policy restored. The 14-day soak began after the feed
  warmed up, the watchdog became healthy, and the maintenance alert state
  cleared.
- The event-evidence change writes its journal under the existing runtime
  storage directory. It does not need to move the account, daily-risk, lease,
  or scanner-state files.

## Read-only deployment facts

The current user-level systemd unit is
`autonomous-futures-qualified-runtime.service`, with `Restart=on-failure`.
Its `WorkingDirectory` and `PYTHONPATH` use
`/opt/autonomous-futures-bot/releases/qualified-runtime`, a symlink that last
resolved to
`/opt/autonomous-futures-bot/.release-qualified-testnet-event-evidence-20261016-dddfea3`.
The prior `.release-web-20261014` directory remains the rollback target.
Runtime state is in `/opt/autonomous-futures-bot/runtime/qualified-testnet`,
outside the release tree. The service's `ExecStartPre` applies leverage settings
and bootstraps daily-risk state before running preflight. A startup failure can
therefore repeat those operations under the current restart policy.

These deployment facts were rechecked at `2026-10-16T16:09:44Z`. Re-read them
immediately before any maintenance; the active link target, systemd
configuration, account, and orders can change.

## Latest read-only soak checkpoint

At `2026-10-16T16:09:44Z`, the qualified Testnet unit was active as PID
`381572`, with `NRestarts=0` and `Restart=on-failure`. The watchdog was
`HEALTHY`, with no active critical or warning alerts. Account reconciliation
was verified and 16.6 seconds old; daily risk was verified, with zero
nonzero positions and zero open orders. The Hawkes model was `STABLE` with
17,489 arrivals.

The portfolio scanner reported `SIDEWAYS` BTC regime and zero ready variants
for `macro-scalper-uninspected-3sym-medium-frequency-v1`. The event-evidence
journal verified with two REST reconciliation records and zero user-data
records (head SHA-256
`6d57970cb1c8b00917cd68f18f68b1a0a0f83086c955f81c3d131cdc6d685456`). The
14-day soak is still in progress; no completed exchange-confirmed lifecycle
has been recorded for any candidate symbol yet.

At the next checkpoint, approximately `2026-10-16T16:15:46Z`, the runtime
remained healthy (`MainPID=381572`, `NRestarts=0`, `Restart=on-failure`), with
verified daily risk, fresh account reconciliation, zero positions and orders,
and stable Hawkes state. The scanner again reported `SIDEWAYS`; all six
variants had `signal_ready=false`, with macro alignment and relative-volume
gates false for each. The service journal contained no warning-or-higher
entries since soak start. This scan showed no eligible setup, so no Testnet
lifecycle has yet been observed.

### Exchange-confirmed lifecycle progress

The ledger had zero user-data records at the `2026-10-16T16:15:13Z`
verification. The Testnet soak therefore has no exchange-confirmed completed
entry-to-exit lifecycle recorded yet:

| Symbol | Completed lifecycles recorded | Required |
| --- | ---: | ---: |
| AVAXUSDT | 0 | 1 |
| ETHUSDT | 0 | 1 |
| SOLUSDT | 0 | 1 |

The ledger verifier checks record integrity and chain continuity; it does not
calculate completed lifecycle counts. For each symbol counted at soak review,
inspect authenticated order updates for a completed entry fill and subsequent
exchange-confirmed exit fill(s), then require a successful later REST
reconciliation showing no remaining position or open order and no unresolved
lifecycle. Record the supporting sequence and reconciliation checkpoint. A
valid hash chain by itself does not satisfy the lifecycle gate.

## Approval and preflight gates

Do not begin maintenance until all of these are true:

1. The source review is recorded and CI is green on the exact final PR head.
   The release commit and all 14 source-file hashes match the manifest. The
   admission manifest hash and AVAX/ETH/SOL portfolio identity also match the
   release target.
2. The user's authorization recorded above covers this exact Testnet source,
   candidate, controlled service cutover, and normal Testnet order submission.
3. A fresh read-only account reconciliation is healthy, with zero nonzero
   positions and zero open orders; the watchdog is healthy; the legacy writer
   remains disabled and inactive; the current qualified-runtime process and
   account lease are identified. Hold the maintenance if any check is stale,
   unknown, or differs from the approved scope.
4. The post-deployment soak is predeclared as 14 calendar days beginning at
   `2026-10-16T16:04:58Z`; the minimum elapsed period ends at
   `2026-10-30T16:04:58Z`. Pass the soak only if all of these numeric criteria
   are met:
   - the event-evidence ledger verifies successfully on every UTC day and at
     the end of the soak;
   - there are zero unresolved private-stream gaps, zero unexplained account,
     position, or order reconciliation differences, zero duplicate writers,
     and zero unowned orders or positions;
   - there are zero CRITICAL watchdog alerts and zero unresolved WARNING
     alerts; every account observation used for a readiness decision is at
     most 30 seconds old and has verified daily-risk state;
   - at least one exchange-confirmed completed entry-to-exit order/fill
     lifecycle is recorded for each of AVAXUSDT, ETHUSDT, and SOLUSDT.

   The period began only after the runtime and watchdog were healthy and the
   temporary restart override was removed. If the period ends before
   all three symbol lifecycles are observed, keep the candidate on Testnet and
   extend the soak until the evidence gate passes. Do not infer order/fill
   behavior from strategy signals or local order state alone.

## Controlled rollout sequence

Only perform these steps during the approved window:

1. Build a complete release directory from the exact approved commit at a new,
   immutable path under `/opt/autonomous-futures-bot/`. Do not edit or delete
   the current release target. Verify every manifest-listed SHA-256, the
   admission-manifest SHA-256, the portfolio ID, Python imports, and required
   runtime assets in the staged directory. Keep runtime storage outside it.
2. Record the exact current symlink target as the rollback target. Add a
   temporary user-unit drop-in setting `Restart=no`, run
   `systemctl --user daemon-reload`, and verify the effective restart policy.
   This bounds startup to one attempt while `ExecStartPre` has side effects.
3. Stop the qualified runtime once. Verify `ActiveState=inactive`,
   `MainPID=0`, and that the account lease is released. Repeat the read-only
   account, position, and order reconciliation after shutdown. Stop the
   rollout if exposure or an order appeared.
4. Atomically replace the `releases/qualified-runtime` symlink with a
   temporary symlink to the staged immutable directory, using a same-filesystem
   rename. Preserve the prior release directory and rollback-target value.
5. Start the unit once. Its `ExecStartPre` will apply leverage and bootstrap
   daily-risk state; record those results. Confirm the preflight, one active
   writer, expected source/admission hashes, fresh account reconciliation,
   zero unresolved positions/orders, and healthy watchdog. If startup fails,
   do not permit automatic retries.
6. Inspect the new `exchange-user-events.jsonl` journal and run
   `uv run --locked python scripts/verify_execution_event_evidence.py <ledger>`
   against the deployed release. Keep missing user-stream events as missing;
   initial REST checkpoints alone do not demonstrate order/fill lifecycle.
7. After the temporary restart override is removed and the original restart
   policy is restored, begin only the predeclared soak. Do not claim Mainnet
   qualification from Testnet runtime evidence.

## Rollback criteria and sequence

Rollback if the staged hashes or admission differ, preflight fails, the runtime
does not become healthy, the private-stream gap is unresolved, account/order
reconciliation differs, the event ledger fails verification, or a critical
watchdog alert appears.

1. Keep `Restart=no`; stop the new runtime and verify `MainPID=0` and lease
   release before changing the link.
2. Reconcile account, positions, and orders. If state is non-flat or unknown,
   do not start another runtime until the operator has resolved ownership and
   protection for that state.
3. Atomically restore the recorded prior symlink target. Start the prior
   release once, confirm its preflight and health, then remove the temporary
   restart drop-in and reload systemd to restore the original policy.
4. Preserve both release directories, journal, systemd journal, and checksums
   for review. Do not delete evidence during rollback.

Rollback restores the prior Testnet code version; it does not reverse exchange
orders, leverage changes, risk-state writes, or external account activity.

## Current status

Testnet deployment and normal Testnet order flow are authorized, and the
controlled cutover is complete. The runtime and watchdog are healthy with the
original restart policy restored. The `2026-10-16T16:15:46Z` checkpoint is
historical; the latest read-only checkpoint is approximately
`2026-10-16T16:42:37Z`. At that check, the qualified unit remained active as
PID `381572` with `NRestarts=0` and `Restart=on-failure`; a direct systemd
check confirmed the legacy writer remained disabled and inactive. The watchdog
was `HEALTHY` without active alerts, account reconciliation was verified and
about 8 seconds old, daily risk was verified, and there were zero positions and
open orders. Hawkes was `STABLE` with 35,471 arrivals. The scanner remained in
a `SIDEWAYS` BTC regime with zero ready variants out of six. The ledger
verified with two REST reconciliation records and zero authenticated user-data
events, so no per-symbol completed lifecycle has been observed. The candidate
receipt has `execution_authority=false`; the current Testnet order-flow scope
comes from the user's separate Testnet approval and does not grant Mainnet
authority. No order was submitted because no variant was ready. Keep the
candidate on Testnet until the full soak criteria pass; Mainnet remains NO-GO.
