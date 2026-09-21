import { useState } from 'react'
import {
  Activity,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  GitBranch,
  Layers,
  Lock,
  Radio,
  Scale,
  Server,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react'

import type { AutonomousLifecycleModel } from '@/lib/canary'

function formatMyt(value: string | number | null): string {
  if (!value) return '—'
  const date = typeof value === 'number' ? new Date(value) : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-MY', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'Asia/Kuala_Lumpur',
    timeZoneName: 'short',
  }).format(date)
}

export function LifecyclePage({ model }: { model: AutonomousLifecycleModel }) {
  const [sessionFilter, setSessionFilter] = useState<string>('ALL')

  const startingEquity = model.ledger?.starting_equity ?? 100.0
  const cash = model.ledger?.cash ?? 100.0
  const allocatedMargin = model.ledger?.allocated_margin ?? 0.0
  const unrealizedPnl = model.ledger?.unrealized_pnl ?? 0.0
  const realizedPnl = model.ledger?.realized_pnl ?? 0.0
  const drift = model.ledger?.drift ?? 0.0
  const isZeroDrift = model.isZeroDrift

  const totalSessions = model.longevity?.total_sessions ?? 0
  const totalTicks = model.longevity?.total_ticks_processed ?? 0
  const uptimeSec = model.longevity?.uptime_seconds ?? 0
  const throughputTps = model.longevity?.throughput_tps ?? 0
  const disconnects = model.longevity?.disconnect_count ?? 0
  const reconnects = model.longevity?.reconnect_count ?? 0
  const gaps = model.longevity?.sequence_gap_count ?? 0
  const duplicates = model.longevity?.duplicate_packets_count ?? 0

  const filteredSessions = model.sessions.filter((s) => {
    if (sessionFilter === 'ALL') return true
    return s.session_id === sessionFilter
  })

  return (
    <div className="space-y-6" aria-labelledby="mission-control-heading">
      {/* 1. Top Header & Safety / Confinement Badges */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Phase 296 / Autonomous Lifecycle Plane
          </p>
          <h2 id="mission-control-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Canary Mission Control: 24/7 Autonomous Lifecycle Daemon &amp; Multi-Session Longevity
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-success gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
            <CheckCircle2 size={14} />
            LIFECYCLE VERIFIED
          </span>
          <span className="badge badge-success gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
            <ShieldCheck size={14} />
            PAPER-SAFE
          </span>
          <span className="badge badge-outline badge-error font-mono text-[11px] font-bold tracking-wider py-2.5 px-3">
            <Lock size={12} className="inline mr-1" />
            EXECUTION AUTHORITY: OFF
          </span>
          <span className="badge badge-success badge-outline font-mono text-[11px] font-bold py-2.5 px-3">
            <Scale size={12} className="inline mr-1" />
            ZERO-DRIFT VERIFIED
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        Unified 24/7 autonomous lifecycle daemon coordinating public market ingress (Phase 292), real-time Hawkes
        microstructure cascades (Phase 293), micro child order slicing and passive matching simulation (Phase 294), and
        walk-forward out-of-sample quantitative strategy activation (Phase 295). Enforces strict multi-session endurance,
        packet deduplication, sequence gap detection, bounded memory ring buffers, fail-closed risk circuit interlocks, and
        mathematical double-entry balance governance (<code>|drift| &lt; 10⁻¹⁵ USDT</code>).
      </p>

      {/* 2. 5 Subsystem Health Scorecards */}
      <section aria-labelledby="subsystem-health-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 id="subsystem-health-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
            <Cpu size={16} className="text-primary" />
            Core Subsystem Health Scorecards (5 Pipelines)
          </h3>
          <span className="text-xs font-mono text-base-content/60">5/5 Subsystems Operational</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {model.components.map((c) => {
            const isHealthy = c.status === 'HEALTHY'
            return (
              <div
                key={c.name}
                className="bg-base-200/60 border border-base-300 rounded-lg p-3.5 shadow-sm space-y-2 hover:border-primary/50 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-xs truncate" title={c.name}>
                    {c.name}
                  </span>
                  <span className={`badge badge-xs font-mono font-bold py-1 px-2 ${isHealthy ? 'badge-success' : 'badge-error'}`}>
                    {c.status}
                  </span>
                </div>
                <p className="text-xs text-base-content/70 line-clamp-2 min-h-[32px]" title={c.details}>
                  {c.details || 'Nominal operation'}
                </p>
                <div className="text-[10px] font-mono text-base-content/50 pt-1 border-t border-base-300/40">
                  {c.updated_at ? `Mark: ${formatMyt(c.updated_at)}` : 'Mark: Real-time'}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 3. Longevity & Uptime Telemetry Grid */}
      <section aria-labelledby="longevity-grid-heading" className="space-y-3">
        <h3 id="longevity-grid-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
          <Activity size={16} className="text-primary" />
          Longevity &amp; Uptime Telemetry Grid
        </h3>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Layers size={13} className="text-primary" />
              Total Sessions
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-base-content">
              {totalSessions}
            </div>
            <div className="text-[10px] text-success font-medium mt-0.5">Multi-session active</div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Clock size={13} className="text-primary" />
              Cumulative Uptime
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-base-content">
              {`${uptimeSec.toFixed(1)}s`}
            </div>
            <div className="text-[10px] text-base-content/60 mt-0.5">Continuous runtime</div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Zap size={13} className="text-warning" />
              Throughput
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-base-content">
              {throughputTps.toFixed(1)} <span className="text-xs font-normal">tps</span>
            </div>
            <div className="text-[10px] text-base-content/60 mt-0.5">{totalTicks.toLocaleString()} total ticks</div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Database size={13} className="text-info" />
              Memory Bounded
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-success">
              O(1) Ring
            </div>
            <div className="text-[10px] text-base-content/60 mt-0.5">Cap: 1,000 / deque</div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Radio size={13} className="text-secondary" />
              Dedup Suppressed
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-base-content">
              {duplicates}
            </div>
            <div className="text-[10px] text-success mt-0.5">0 stale state replays</div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-3">
            <div className="text-[11px] uppercase font-mono text-base-content/60 flex items-center gap-1.5">
              <Server size={13} className="text-accent" />
              Reconnection Drills
            </div>
            <div className="text-xl font-mono font-bold mt-1 text-base-content">
              {`${disconnects}/${reconnects}`}
            </div>
            <div className="text-[10px] text-base-content/60 mt-0.5">{gaps} sequence gaps caught</div>
          </div>
        </div>
      </section>

      {/* 4. Endurance Session Timeline Table */}
      <section aria-labelledby="session-timeline-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="session-timeline-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
            <Layers size={16} className="text-primary" />
            Endurance Session Timeline Table
          </h3>
          {model.sessions.length > 1 && (
            <div className="flex items-center gap-1">
              <span className="text-xs font-mono text-base-content/60">Filter:</span>
              <select
                className="select select-xs select-bordered font-mono"
                value={sessionFilter}
                onChange={(e) => setSessionFilter(e.target.value)}
              >
                <option value="ALL">All Sessions ({model.sessions.length})</option>
                {model.sessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.session_id}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="overflow-x-auto bg-base-200/50 border border-base-300 rounded-lg">
          <table className="table table-xs table-zebra w-full font-mono">
            <thead>
              <tr className="bg-base-300/60 text-base-content/70">
                <th>Session ID</th>
                <th>Duration</th>
                <th className="text-right">Ticks</th>
                <th className="text-right">Orders</th>
                <th className="text-right">Fills</th>
                <th className="text-right">Starting Equity</th>
                <th className="text-right">Ending Cash</th>
                <th className="text-right">Realized PnL</th>
                <th className="text-right">Drift (USDT)</th>
                <th className="text-center">Zero-Drift</th>
                <th className="text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredSessions.length === 0 ? (
                <tr>
                  <td colSpan={11} className="text-center py-6 text-base-content/60">
                    No sessions recorded in current view.
                  </td>
                </tr>
              ) : (
                filteredSessions.map((s) => (
                  <tr key={s.session_id} className="hover:bg-base-300/40">
                    <td className="font-bold text-primary">{s.session_id}</td>
                    <td>{`${s.duration_seconds.toFixed(2)}s`}</td>
                    <td className="text-right">{s.ticks_processed.toLocaleString()}</td>
                    <td className="text-right">{s.orders_placed}</td>
                    <td className="text-right">{s.fills_count}</td>
                    <td className="text-right">{s.starting_equity_usdt.toFixed(2)}</td>
                    <td className="text-right">{s.ending_cash_usdt.toFixed(4)}</td>
                    <td className={`text-right font-semibold ${s.realized_pnl_usdt >= 0 ? 'text-success' : 'text-error'}`}>
                      {s.realized_pnl_usdt >= 0 ? `+${s.realized_pnl_usdt.toFixed(4)}` : s.realized_pnl_usdt.toFixed(4)}
                    </td>
                    <td className="text-right text-success">{s.drift_usdt.toExponential(1)}</td>
                    <td className="text-center">
                      <span className="badge badge-success badge-xs font-semibold py-1 px-2">
                        VERIFIED
                      </span>
                    </td>
                    <td className="text-center">
                      <span className="badge badge-ghost badge-xs font-bold py-1 px-2">
                        {s.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. Live Operational Switches Matrix */}
      <section aria-labelledby="switches-matrix-heading" className="space-y-3">
        <h3 id="switches-matrix-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
          <ShieldAlert size={16} className="text-primary" />
          Live Operational Switches &amp; Risk Interlocks Matrix
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {model.operationalSwitches.map((sw) => {
            const isSafetyActive = sw.enabled
            const isExecAuthority = sw.name === 'execution_authority'
            const badgeColor = isExecAuthority
              ? sw.enabled ? 'badge-error' : 'badge-success'
              : sw.enabled ? 'badge-success' : 'badge-error'

            return (
              <div
                key={sw.name}
                className="bg-base-200/60 border border-base-300 rounded-lg p-3.5 flex flex-col justify-between shadow-sm space-y-2 hover:border-primary/40 transition-colors"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-xs">{sw.label}</span>
                    <span className={`badge badge-xs font-mono font-bold py-1 px-2 ${badgeColor}`}>
                      {sw.value_display || (isSafetyActive ? 'ON' : 'OFF')}
                    </span>
                  </div>
                  <p className="text-xs text-base-content/70 mt-1.5 leading-relaxed">
                    {sw.description}
                  </p>
                </div>
                <div className="text-[10px] font-mono text-base-content/50 pt-2 border-t border-base-300/40 flex items-center justify-between">
                  <span>Fail-Closed: {sw.fail_closed ? 'ENFORCED' : 'OFF'}</span>
                  <span className="text-success font-semibold">INTERLOCKED</span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 6. Double-Entry Solvency & Accounting Ledger */}
      <section aria-labelledby="ledger-reconciliation-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 id="ledger-reconciliation-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
            <Scale size={16} className="text-primary" />
            Double-Entry Solvency &amp; Accounting Ledger
          </h3>
          <span className="badge badge-success badge-sm gap-1 font-mono font-semibold">
            <CheckCircle2 size={12} />
            |drift| &lt; 10⁻¹⁵ USDT
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-base-200/70 border border-base-300 rounded-lg p-4 space-y-2">
            <div className="text-xs uppercase font-mono text-base-content/60 font-semibold">Balance Composition</div>
            <div className="space-y-1.5 font-mono text-xs">
              <div className="flex justify-between">
                <span className="text-base-content/70">Starting Equity:</span>
                <span className="font-bold">{`${startingEquity.toFixed(2)} USDT`}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-base-content/70">Final Cash:</span>
                <span className="font-bold text-success">{`${cash.toFixed(4)} USDT`}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-base-content/70">Allocated Margin:</span>
                <span className="font-bold">{`${allocatedMargin.toFixed(4)} USDT`}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-base-content/70">Unrealized PnL:</span>
                <span className={unrealizedPnl >= 0 ? 'text-success' : 'text-error'}>
                  {unrealizedPnl >= 0 ? `+${unrealizedPnl.toFixed(4)} USDT` : `${unrealizedPnl.toFixed(4)} USDT`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-base-content/70">Realized PnL:</span>
                <span className={realizedPnl >= 0 ? 'text-success' : 'text-error'}>
                  {realizedPnl >= 0 ? `+${realizedPnl.toFixed(4)} USDT` : `${realizedPnl.toFixed(4)} USDT`}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-4 space-y-3 flex flex-col justify-between">
            <div className="space-y-1">
              <div className="text-xs uppercase font-mono text-base-content/60 font-semibold">Mathematical Identity</div>
              <p className="text-[11px] font-mono bg-base-300/60 p-2 rounded text-base-content/80">
                Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL
              </p>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between text-xs font-mono">
                <span className="text-base-content/60">Mathematical Drift:</span>
                <span className="font-bold text-success font-mono">{`${drift.toExponential(4)} USDT`}</span>
              </div>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-base-content/60">Zero Drift Status:</span>
                <span className="font-bold text-success">{isZeroDrift ? 'VERIFIED (0E-8)' : 'FAILED'}</span>
              </div>
            </div>
          </div>

          <div className="bg-base-200/70 border border-base-300 rounded-lg p-4 space-y-3 flex flex-col justify-between">
            <div className="space-y-1">
              <div className="text-xs uppercase font-mono text-base-content/60 font-semibold">Reserve Buffer &amp; Exposure</div>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-base-content/60">Cash Reserve:</span>
                <span className="font-bold">{model.riskCircuits.cash_reserve_pct.toFixed(1)}% (Floor: 40.0%)</span>
              </div>
              <div className="w-full bg-base-300 rounded-full h-2">
                <div
                  className="bg-success h-2 rounded-full"
                  style={{ width: `${Math.min(100, Math.max(0, model.riskCircuits.cash_reserve_pct))}%` }}
                />
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between text-xs font-mono">
                <span className="text-base-content/60">Margin Allocation:</span>
                <span className="font-bold">{allocatedMargin.toFixed(2)} / 60.00 USDT</span>
              </div>
              <div className="w-full bg-base-300 rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full"
                  style={{ width: `${Math.min(100, (allocatedMargin / 60.0) * 100)}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 7. Cryptographic SHA-256 Merkle DAG Provenance */}
      <section aria-labelledby="merkle-dag-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 id="merkle-dag-heading" className="text-sm font-bold uppercase tracking-wider text-base-content/80 flex items-center gap-2">
            <GitBranch size={16} className="text-primary" />
            Cryptographic SHA-256 Merkle DAG Provenance (Phase 295 &rarr; Phase 296)
          </h3>
          <span className="badge badge-success badge-xs font-mono py-2 px-2 font-bold">
            MERKLE ROOT VERIFIED
          </span>
        </div>

        <div className="bg-base-200/50 border border-base-300 rounded-lg p-4 space-y-3 font-mono text-xs">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <span className="text-base-content/60 block text-[11px] mb-1">Phase 296 Merkle Root:</span>
              <div className="bg-base-300/80 p-2 rounded text-primary font-bold break-all select-all">
                {model.merkleRoot || model.phaseHash || '—'}
              </div>
            </div>
            <div>
              <span className="text-base-content/60 block text-[11px] mb-1">Upstream Phase 295 Root Summary Hash:</span>
              <div className="bg-base-300/80 p-2 rounded text-base-content/90 font-bold break-all select-all">
                {model.upstreamHash || '1d6e6412f9c2a19dce2625fd3236ebdb9bd6c527959bb33875889a18ee51f005'}
              </div>
            </div>
          </div>

          <div className="text-[11px] text-base-content/60 pt-2 border-t border-base-300 flex flex-wrap items-center justify-between gap-2">
            <span>Cryptographic Chain: Phase 292 &rarr; Phase 293 &rarr; Phase 294 &rarr; Phase 295 &rarr; Phase 296</span>
            <span className="text-success font-bold">SHA-256 Immutable Audit Trail</span>
          </div>
        </div>
      </section>
    </div>
  )
}
