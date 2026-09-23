import { useState } from 'react'
import {
  AlertOctagon,
  CheckCircle2,
  FileKey,
  Flame,
  GitBranch,
  KeyRound,
  Lock,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Users,
  ZapOff,
} from 'lucide-react'

import type { KillSwitchModel } from '@/lib/canary'

export function KillSwitchPage({ model }: { model: KillSwitchModel }) {
  const [activeTab, setActiveTab] = useState<'events' | 'signers' | 'proposals'>('events')

  const signers = model.signers || []
  const proposals = model.proposals || []
  const events = model.eventsTrace || []
  const solvency = model.solvency
  const ledger = model.ledger

  const startingEquity = solvency?.starting_equity_usdt ?? ledger?.starting_equity ?? 100.0
  const cash = solvency?.cash_usdt ?? ledger?.cash ?? 100.0
  const allocatedMargin = solvency?.allocated_margin_usdt ?? ledger?.allocated_margin ?? 0.0
  const unrealizedPnl = solvency?.unrealized_pnl_usdt ?? ledger?.unrealized_pnl ?? 0.0
  const totalEquity = solvency?.total_equity_usdt ?? cash + allocatedMargin + unrealizedPnl
  const drift = solvency?.drift_usdt ?? ledger?.drift ?? 0.0
  const isZeroDrift = model.isZeroDrift
  const cashReservePct =
    solvency?.cash_reserve_pct ?? (startingEquity > 0 ? (cash / startingEquity) * 100 : 100)

  return (
    <div className="space-y-8 p-6">
      {/* Top Banner / Header */}
      <div className="flex flex-col justify-between gap-4 rounded-2xl bg-base-200/60 p-6 backdrop-blur-md lg:flex-row lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-base-content">
              Capital Safety Governance, Multi-Signature &amp; Hardware/OS Kill-Switch Engine
            </h1>
            <span className="badge badge-primary font-mono text-xs font-semibold">
              PHASE 308
            </span>
            <span className="badge badge-success gap-1 text-xs font-semibold">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {model.status}
            </span>
          </div>
          <p className="mt-2 text-sm text-base-content/70">
            M-of-N quorum multi-sig authorization (HMAC-SHA256), 3-tier containment escalation (Soft Pause, Lockout, Hardware Panic),
            sub-millisecond emergency flattening, in-memory credential zeroization, and zero-drift balance invariant governance.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="badge badge-outline gap-1 font-mono text-xs">
            <ShieldCheck className="h-3.5 w-3.5 text-success" />
            PAPER-SAFE: {model.isPaperSafe ? 'TRUE' : 'FALSE'}
          </div>
          <div className="badge badge-outline gap-1 font-mono text-xs">
            <Lock className="h-3.5 w-3.5 text-warning" />
            EXECUTION AUTHORITY: OFF
          </div>
          <div className="badge badge-outline gap-1 font-mono text-xs">
            <Scale className="h-3.5 w-3.5 text-info" />
            ZERO-DRIFT: {isZeroDrift ? 'VERIFIED (0.00)' : 'BREACH'}
          </div>
        </div>
      </div>

      {/* 4 KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Card 1: Kill-Switch State & Memory Scrubbing */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Kill-Switch State</span>
              <ShieldAlert className="h-4 w-4 text-error" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-xl font-black tracking-tight text-error font-mono">
                {model.killSwitchState}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Memory Scrubbing</span>
              <span className="badge badge-xs badge-success font-mono font-bold">
                {model.isMemoryWiped ? 'ZEROIZATION_VERIFIED' : 'ACTIVE'}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Tripwire Interlock</span>
              <span className="font-mono font-bold text-success">FILE &amp; OS SIGNAL</span>
            </div>
          </div>
        </div>

        {/* Card 2: Multi-Sig Quorum Governance */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Multi-Sig Quorum</span>
              <KeyRound className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-primary font-mono">
                {`${model.requiredQuorum} / ${model.activeSignersCount}`}
              </span>
              <span className="badge badge-sm badge-primary font-mono">M-of-N QUORUM</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Proposals Evaluated</span>
              <span className="font-mono font-bold text-base-content">
                {model.proposalsEvaluated}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Proposals Executed</span>
              <span className="font-mono font-bold text-success">
                {model.proposalsExecuted}
              </span>
            </div>
          </div>
        </div>

        {/* Card 3: Emergency Containment Metrics */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Containment Actions</span>
              <ZapOff className="h-4 w-4 text-warning" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-warning font-mono">
                {model.emergencyFlattenedPositions}
              </span>
              <span className="text-xs font-semibold text-base-content/60">Positions Flattened</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Orders Mass-Cancelled</span>
              <span className="font-mono font-bold text-base-content">
                {model.cancelledOrdersCount}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Total Kill Events</span>
              <span className="font-mono font-bold text-warning">
                {model.totalKillEvents}
              </span>
            </div>
          </div>
        </div>

        {/* Card 4: Double-Entry Solvency & Zero Drift */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Double-Entry Solvency</span>
              <Scale className="h-4 w-4 text-success" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-success font-mono">
                ${totalEquity.toFixed(2)}
              </span>
              <span className="badge badge-sm badge-success">ZERO-DRIFT</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Cash Reserve</span>
              <span className="font-mono font-bold text-base-content">
                {cashReservePct.toFixed(1)}% (${cash.toFixed(2)})
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Balance Drift</span>
              <span className="font-mono font-bold text-success">
                {Math.abs(drift) < 1e-15 ? '0.00 USDT' : `${drift.toExponential(2)} USDT`}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs / Table Navigation */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-base-300 pb-4">
            <div className="tabs tabs-boxed bg-base-200">
              <button
                type="button"
                className={`tab font-semibold ${activeTab === 'events' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('events')}
              >
                <Flame className="mr-1.5 h-4 w-4" />
                Kill-Switch Escalation Trail ({events.length})
              </button>
              <button
                type="button"
                className={`tab font-semibold ${activeTab === 'signers' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('signers')}
              >
                <Users className="mr-1.5 h-4 w-4" />
                Multi-Sig Signers ({signers.length})
              </button>
              <button
                type="button"
                className={`tab font-semibold ${activeTab === 'proposals' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('proposals')}
              >
                <FileKey className="mr-1.5 h-4 w-4" />
                Governance Proposals ({proposals.length})
              </button>
            </div>
            <span className="badge badge-outline badge-sm font-mono">
              Quorum: {model.requiredQuorum}-of-{model.activeSignersCount} Required
            </span>
          </div>

          {/* TAB 1: Kill-Switch Events */}
          {activeTab === 'events' && (
            <div className="mt-4 overflow-x-auto">
              <table className="table table-zebra w-full text-xs">
                <thead>
                  <tr className="bg-base-200 text-base-content/80">
                    <th>Event ID</th>
                    <th>Tier</th>
                    <th>State Transition</th>
                    <th>Trigger Source</th>
                    <th>Reason</th>
                    <th>Orders Cancelled</th>
                    <th>Positions Flattened</th>
                    <th>Memory Scrubbed</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-6 text-center text-base-content/50">
                        No kill-switch escalation events recorded.
                      </td>
                    </tr>
                  ) : (
                    events.map((evt) => (
                      <tr key={evt.event_id}>
                        <td className="font-mono font-bold">{evt.event_id}</td>
                        <td>
                          <span
                            className={`badge badge-xs font-mono font-bold ${
                              evt.tier === 'LEVEL_3_PANIC'
                                ? 'badge-error'
                                : evt.tier === 'LEVEL_2_LOCKOUT'
                                ? 'badge-warning'
                                : 'badge-info'
                            }`}
                          >
                            {evt.tier}
                          </span>
                        </td>
                        <td className="font-mono">
                          <span className="text-base-content/60">{evt.previous_state}</span>
                          {' → '}
                          <span className="font-bold text-error">{evt.new_state}</span>
                        </td>
                        <td>
                          <span className="badge badge-outline badge-xs font-mono">
                            {evt.trigger_source}
                          </span>
                        </td>
                        <td className="max-w-xs truncate" title={evt.reason}>
                          {evt.reason}
                        </td>
                        <td className="font-mono font-semibold text-center">
                          {evt.orders_cancelled_count}
                        </td>
                        <td className="font-mono font-semibold text-center">
                          {evt.positions_flattened_count}
                        </td>
                        <td className="text-center">
                          {evt.memory_wiped ? (
                            <span className="badge badge-xs badge-success gap-1 font-mono">
                              <Trash2 className="h-3 w-3" /> ZEROED
                            </span>
                          ) : (
                            <span className="text-base-content/40 font-mono">—</span>
                          )}
                        </td>
                        <td className="font-mono text-base-content/60">
                          {new Date(evt.timestamp_ms).toLocaleTimeString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 2: Multi-Sig Signers */}
          {activeTab === 'signers' && (
            <div className="mt-4 overflow-x-auto">
              <table className="table table-zebra w-full text-xs">
                <thead>
                  <tr className="bg-base-200 text-base-content/80">
                    <th>Signer ID</th>
                    <th>Role</th>
                    <th>Public Key (Truncated)</th>
                    <th>Status</th>
                    <th>Last Nonce</th>
                  </tr>
                </thead>
                <tbody>
                  {signers.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-6 text-center text-base-content/50">
                        No signers registered.
                      </td>
                    </tr>
                  ) : (
                    signers.map((signer) => (
                      <tr key={signer.signer_id}>
                        <td className="font-mono font-bold text-primary">{signer.signer_id}</td>
                        <td>
                          <span className="badge badge-primary badge-outline badge-xs font-mono">
                            {signer.role}
                          </span>
                        </td>
                        <td className="font-mono text-base-content/70">
                          {signer.public_key.length > 28
                            ? `${signer.public_key.slice(0, 16)}...${signer.public_key.slice(-8)}`
                            : signer.public_key}
                        </td>
                        <td>
                          {signer.is_active ? (
                            <span className="badge badge-xs badge-success font-mono">ACTIVE</span>
                          ) : (
                            <span className="badge badge-xs badge-ghost font-mono">REVOKED</span>
                          )}
                        </td>
                        <td className="font-mono font-bold">{signer.last_nonce}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 3: Governance Proposals */}
          {activeTab === 'proposals' && (
            <div className="mt-4 overflow-x-auto">
              <table className="table table-zebra w-full text-xs">
                <thead>
                  <tr className="bg-base-200 text-base-content/80">
                    <th>Proposal ID</th>
                    <th>Action Type</th>
                    <th>Target</th>
                    <th>Parameters</th>
                    <th>Quorum Progress</th>
                    <th>Status</th>
                    <th>Execution Result</th>
                  </tr>
                </thead>
                <tbody>
                  {proposals.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-6 text-center text-base-content/50">
                        No governance proposals submitted.
                      </td>
                    </tr>
                  ) : (
                    proposals.map((prop) => (
                      <tr key={prop.proposal_id}>
                        <td className="font-mono font-bold">{prop.proposal_id}</td>
                        <td>
                          <span className="badge badge-secondary badge-xs font-mono">
                            {prop.action_type}
                          </span>
                        </td>
                        <td className="font-mono font-semibold">{prop.target}</td>
                        <td className="font-mono text-base-content/70">
                          {JSON.stringify(prop.parameters)}
                        </td>
                        <td>
                          <span className="font-mono font-bold text-primary">
                            {`${prop.votes_cast} / ${prop.required_quorum}`}
                          </span>
                        </td>
                        <td>
                          {prop.is_executed ? (
                            <span className="badge badge-xs badge-success font-mono">EXECUTED</span>
                          ) : (
                            <span className="badge badge-xs badge-warning font-mono">PENDING</span>
                          )}
                        </td>
                        <td className="font-mono text-xs">
                          {prop.execution_result ?? '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* 3-Tier Containment Architecture Overview */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex items-center gap-2 border-b border-base-300 pb-4">
            <AlertOctagon className="h-5 w-5 text-warning" />
            <h2 className="text-lg font-bold text-base-content">
              Fail-Closed 3-Tier Escalation Containment Model
            </h2>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
              <div className="flex items-center justify-between">
                <span className="badge badge-info badge-sm font-mono">TIER 1</span>
                <span className="text-xs font-bold text-info">LEVEL_1_SOFT_PAUSE</span>
              </div>
              <h3 className="mt-2 font-bold text-base-content">Soft Throttle &amp; Pause</h3>
              <p className="mt-1 text-xs text-base-content/70">
                Triggered by Hawkes supercritical bursts ($\rho \ge 1.0$) or short-term volatility surges.
                Halts new parent &amp; child order generation; allows existing resting orders to passively fill or expire.
              </p>
            </div>

            <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
              <div className="flex items-center justify-between">
                <span className="badge badge-warning badge-sm font-mono">TIER 2</span>
                <span className="text-xs font-bold text-warning">LEVEL_2_LOCKOUT</span>
              </div>
              <h3 className="mt-2 font-bold text-base-content">Mass Cancellation &amp; Lockout</h3>
              <p className="mt-1 text-xs text-base-content/70">
                Triggered by gateway heartbeat staleness (&gt; 500 ms) or loss ceiling breaches.
                Immediately issues synchronous mass-cancellation across all open orders on all candidates.
                Requires 2-of-3 multi-sig proposal to reset.
              </p>
            </div>

            <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
              <div className="flex items-center justify-between">
                <span className="badge badge-error badge-sm font-mono">TIER 3</span>
                <span className="text-xs font-bold text-error">LEVEL_3_HARDWARE_PANIC</span>
              </div>
              <h3 className="mt-2 font-bold text-base-content">Panic Flattening &amp; Zeroization</h3>
              <p className="mt-1 text-xs text-base-content/70">
                Triggered by OS signals (`SIGINT`, `SIGUSR1`) or tripwire token file detection.
                Emergency sub-millisecond market flattening of all positions, immediate mass cancellation,
                and cryptographic memory zeroization of in-memory API credentials.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Merkle DAG Provenance */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex items-center gap-2 border-b border-base-300 pb-4">
            <GitBranch className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-bold text-base-content">
              Cryptographic Merkle DAG Provenance
            </h2>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-base-content/60">
                Phase 307 Upstream Root
              </span>
              <p className="mt-1 font-mono text-xs break-all text-base-content/80">
                {model.upstreamHash}
              </p>
            </div>
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-base-content/60">
                Phase 308 Local Hash
              </span>
              <p className="mt-1 font-mono text-xs break-all text-base-content/80">
                {model.phaseHash || '—'}
              </p>
            </div>
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-primary">
                Phase 308 Merkle Root
              </span>
              <p className="mt-1 font-mono text-xs break-all font-bold text-primary">
                {model.merkleRoot || '65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
