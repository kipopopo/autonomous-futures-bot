import { Activity, AlertTriangle, CheckCircle2, Cpu, Gauge, Zap } from 'lucide-react'

import type { HawkesSnapshot, MicrostructureModel } from '@/lib/canary'

function formatMyt(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
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

function regimeBadge(regime: string) {
  if (regime.includes('SUPERCRITICAL')) {
    return (
      <span className="badge badge-error gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
        <AlertTriangle size={14} /> SUPERCRITICAL CASCADE
      </span>
    )
  }
  if (regime.includes('SEVERE') || regime.includes('ELEVATED')) {
    return (
      <span className="badge badge-warning gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
        <AlertTriangle size={14} /> SEVERE HAWKES CONTROLS
      </span>
    )
  }
  return (
    <span className="badge badge-success gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
      <CheckCircle2 size={14} /> NOMINAL STABILITY
    </span>
  )
}

function formatCascadeState(state: string): string {
  if (state.includes('SEVERE_PREDATORY_FRONT_RUNNING')) return 'PREDATORY RUNAWAY'
  if (state.includes('SUPERCRITICAL_CASCADE_RUNAWAY')) return 'SUPERCRITICAL RUNAWAY'
  return state.replace(/_/g, ' ')
}

export function MicrostructurePage({ model }: { model: MicrostructureModel }) {
  const isElevated = model.isHawkesElevated
  const isSupercritical = model.isSupercritical

  return (
    <div className="space-y-6" aria-labelledby="microstructure-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Microstructure Plane / Telemetry Engine
          </p>
          <h2 id="microstructure-heading" className="text-xl sm:text-2xl font-bold tracking-tight mt-0.5">
            Hawkes Process Jump Intensity &amp; Order Cascades
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {regimeBadge(model.currentRegime)}
        </div>
      </div>

      <p className="text-sm text-base-content/70 leading-relaxed">
        Observational telemetry modeling multivariate mutually exciting jump arrival cascades across staged candidates
        (<code className="badge badge-sm badge-neutral font-mono">BTCUSDT</code>,{' '}
        <code className="badge badge-sm badge-neutral font-mono">ETHUSDT</code>,{' '}
        <code className="badge badge-sm badge-neutral font-mono">SOLUSDT</code>). Real-time spectral radius detection triggers
        passive limit offset cushioning and pacing throttling.
      </p>

      {/* Primary Fact Grid: Responsive Grid to prevent cramping */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 w-full">
        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Max Spectral Radius</span>
            <span className="text-secondary"><Gauge size={18} /></span>
          </div>
          <div className={`font-mono text-2xl font-bold mt-1.5 ${isSupercritical ? 'text-error' : isElevated ? 'text-warning' : 'text-success'}`}>
            {model.maxSpectralRadius.toFixed(6)}
          </div>
          <div className="text-xs text-base-content/60 mt-1">
            {isSupercritical
              ? 'Runaway cascade boundary (ρ ≥ 1.0) breached'
              : isElevated
                ? 'Elevated hazard cushion (ρ ≥ 0.85) active'
                : 'Stable subcritical regime (ρ < 0.85)'}
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Peak Jump Intensity</span>
            <span className="text-warning"><Zap size={18} /></span>
          </div>
          <div className="font-mono text-2xl font-bold mt-1.5 text-warning">
            {model.maxJumpIntensity.toFixed(4)} <span className="text-sm font-normal text-base-content/70">λ/s</span>
          </div>
          <div className="text-xs text-base-content/60 mt-1">Dynamic order arrival rate (λᵢ(t))</div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Staged Candidates</span>
            <span className="text-primary"><Cpu size={18} /></span>
          </div>
          <div className="font-mono text-2xl font-bold mt-1.5 text-primary">{model.candidates.length}</div>
          <div className="flex flex-wrap gap-1 mt-1 font-mono">
            {model.candidates.map((sym) => (
              <span key={sym} className="badge badge-sm badge-neutral font-mono text-[10px]">{sym}</span>
            ))}
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Phase Telemetry</span>
            <span className="text-success"><Activity size={18} /></span>
          </div>
          <div className="font-mono text-2xl font-bold mt-1.5 uppercase text-base-content">{model.phase}</div>
          <div className="text-xs text-success mt-1">Cryptographic DAG verified</div>
        </div>
      </div>

      {/* Candidates Detail Table */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">Candidate Registry Manifest v2</p>
              <h3 className="text-base font-bold">Candidate Microstructure States</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              {Object.keys(model.latestBySymbol).length} symbols tracked
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-zebra table-sm w-full font-sans">
              <thead className="bg-base-300/60 text-base-content/70 text-xs font-mono uppercase">
                <tr>
                  <th className="min-w-[80px]">Symbol</th>
                  <th className="min-w-[95px]">Jump (λ)</th>
                  <th className="min-w-[90px]">Branching</th>
                  <th className="min-w-[95px]">Spectral (ρ)</th>
                  <th className="min-w-[90px]">Alpha (α)</th>
                  <th className="min-w-[80px]">Pacing</th>
                  <th className="min-w-[85px]">Cushion</th>
                  <th className="min-w-[150px]">Cascade State</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {Object.entries(model.latestBySymbol).map(([symbol, item]: [string, HawkesSnapshot]) => (
                  <tr key={symbol} className="hover">
                    <td className="font-bold text-sm">{symbol}</td>
                    <td className="font-mono">{item.jump_intensity}</td>
                    <td className="font-mono">{item.branching_ratio}</td>
                    <td className="font-mono">{item.spectral_radius}</td>
                    <td className="font-mono">{item.self_excitation_alpha}</td>
                    <td className="font-mono">{item.pacing_interval_ms} ms</td>
                    <td className="font-mono">{item.limit_offset_cushion_bps} bps</td>
                    <td>
                      <span
                        title={item.cascade_state}
                        className={`badge badge-sm py-2 px-2.5 font-semibold text-[11px] whitespace-nowrap shadow-sm ${
                          item.regime.includes('SUPERCRITICAL')
                            ? 'badge-error'
                            : item.regime.includes('SEVERE')
                              ? 'badge-warning'
                              : 'badge-success'
                        }`}
                      >
                        {formatCascadeState(item.cascade_state)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Hawkes Snapshots Historical Telemetry */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">Event Log</p>
              <h3 className="text-base font-bold">Recent Hawkes Cascade Snapshots</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              {model.snapshots.length} recorded events
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-zebra table-sm w-full font-sans">
              <thead className="bg-base-300/60 text-base-content/70 text-xs font-mono uppercase">
                <tr>
                  <th className="min-w-[180px]">Time (MYT)</th>
                  <th className="min-w-[90px]">Track ID</th>
                  <th className="min-w-[100px]">Symbol</th>
                  <th className="min-w-[180px]">Regime</th>
                  <th className="min-w-[120px]">Spectral Radius</th>
                  <th className="min-w-[90px]">Pacing</th>
                  <th className="min-w-[130px]">Limit Offset Cushion</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {model.snapshots.map((snap) => (
                  <tr key={snap.record_id} className="hover">
                    <td className="font-mono text-xs">{formatMyt(snap.timestamp_utc)}</td>
                    <td><code className="badge badge-xs badge-neutral font-mono">{snap.track_id}</code></td>
                    <td className="font-bold">{snap.symbol}</td>
                    <td>{regimeBadge(snap.regime)}</td>
                    <td className="font-mono">{snap.spectral_radius}</td>
                    <td className="font-mono">{snap.pacing_interval_ms} ms</td>
                    <td className="font-mono">{snap.limit_offset_cushion_bps} bps</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
