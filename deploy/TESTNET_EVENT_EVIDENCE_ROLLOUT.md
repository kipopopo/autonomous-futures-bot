# Controlled Testnet event-evidence rollout

**Status: PREPARED, NOT APPROVED, NOT DEPLOYED.** This plan is limited to
Testnet and the already deployed portfolio. It is not a Mainnet release plan.

## Release identity and scope

- Candidate: `macro-scalper-uninspected-3sym-medium-frequency-v1`
  (`AVAXUSDT`, `ETHUSDT`, `SOLUSDT`). The user confirmed this candidate as the
  target for future qualification and deployment work. That confirmation does
  not authorize service changes or exchange orders.
- Source: `dddfea3cac6d21fe906969d3805545cd5942293a`.
- Release manifest:
  [`release-manifests/qualified-testnet-event-evidence-20261016.json`](release-manifests/qualified-testnet-event-evidence-20261016.json).
- The manifest remains `TESTNET_DEPLOYMENT_NOT_APPROVED`, with
  `release_approved: false` and `deployed: false`.
- The event-evidence change writes its journal under the existing runtime
  storage directory. It does not need to move the account, daily-risk, lease,
  or scanner-state files.

## Read-only deployment facts

The current user-level systemd unit is
`autonomous-futures-qualified-runtime.service`, with `Restart=on-failure`.
Its `WorkingDirectory` and `PYTHONPATH` use
`/opt/autonomous-futures-bot/releases/qualified-runtime`, a symlink that last
resolved to `/opt/autonomous-futures-bot/.release-web-20261014`. Runtime state
is in `/opt/autonomous-futures-bot/runtime/qualified-testnet`, outside the
release tree. The service's `ExecStartPre` applies leverage settings and
bootstraps daily-risk state before running preflight. A startup failure can
therefore repeat those operations under the current restart policy.

These are inspection results from 2026-10-16. Re-read them immediately before
any maintenance; the active link target, systemd configuration, account, and
orders can change.

## Approval and preflight gates

Do not begin maintenance until all of these are true:

1. The final PR head has review approval and green CI. The release commit and
   all 14 source-file hashes match the manifest. The admission manifest hash
   and AVAX/ETH/SOL portfolio identity also match the release target.
2. The operator explicitly authorizes this exact Testnet maintenance window,
   source revision, and candidate. The normal runtime scans for entries and
   can submit Testnet orders when its strategy signals. Approval must cover
   that behavior. The current runtime has no observation-only switch; if the
   intended permission is limited to read-only collection, add and review such
   a mode before deployment.
3. A fresh read-only account reconciliation is healthy, with zero nonzero
   positions and zero open orders; the watchdog is healthy; the legacy writer
   remains disabled and inactive; the current qualified-runtime process and
   account lease are identified. Hold the maintenance if any check is stale,
   unknown, or differs from the approved scope.
4. Predeclare the Testnet soak duration and numeric acceptance criteria.
   Include ledger verification, account/order reconciliation, private-stream
   gaps, watchdog status, and any exchange-confirmed order/fill evidence.

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

## Current blocker

The release is unapproved and the protected service has not been changed.
Confirm green CI for the exact proposed release PR head immediately before
rollout. The current runtime can trade on Testnet and there is no
observation-only mode. Explicit Testnet maintenance and order-flow
authorization are therefore still required before rollout.
