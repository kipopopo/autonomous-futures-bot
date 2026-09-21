import { useMemo } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Radio,
  ShieldAlert,
  Zap,
} from 'lucide-react'

import { CrossExcitationMatrix } from '@/components/cross-excitation-matrix'
import { SpectralRadiusChart } from '@/components/spectral-radius-chart'
import type { MicrostructureModel } from '@/lib/canary'
import type { TelemetryState } from '@/lib/websocket'

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
      <span className="badge badge-error gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm animate-pulse">
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

export interface MicrostructurePageProps {
  model: MicrostructureModel
  telemetry?: TelemetryState
}

export function MicrostructurePage({ model, telemetry }: MicrostructurePageProps) {
  const liveHawkes = telemetry?.latestHawkes
  const currentRegime = liveHawkes?.regimes?.SOLUSDT || telemetry?.activeRegime || model.currentRegime

  const currentSpectralRadius = useMemo(() => {
    if (liveHawkes?.spectral_radius) {
      const parsed = parseFloat(liveHawkes.spectral_radius)
      if (Number.isFinite(parsed)) return parsed
    }
    return model.maxSpectralRadius
  }, [liveHawkes, model.maxSpectralRadius])

  const isSupercritical =
    telemetry?.isSupercritical ||
    model.isSupercritical ||
    currentSpectralRadius >= 1.0 ||
    currentRegime.includes('SUPERCRITICAL')

  const isElevated =
    model.isHawkesElevated ||
    currentSpectralRadius >= 0.85 ||
    currentRegime.includes('SEVERE') ||
    currentRegime.includes('ELEVATED')

  const isLiveStreaming = telemetry?.status === 'STREAMING'

  // Dynamic pacing and cushioning from live telemetry
  const pacingMs = liveHawkes?.pacing_intervals_ms?.SOLUSDT ?? (isSupercritical || isElevated ? 1000 : 100)
  const cushionBps = liveHawkes?.limit_offset_cushions_bps?.SOLUSDT ?? (isSupercritical ? '5.00' : isElevated ? '2.00' : '0.00')

  return (
    <div className="space-y-6" aria-labelledby="microstructure-heading">
      {/* Supercritical Runaway Banner */}
      {isSupercritical && (
        <div
          className="alert alert-error font-bold shadow-xl animate-pulse flex items-center justify-between"
          role="alert"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle size={24} className="shrink-0" />
            <div>
              <div className="text-base font-extrabold tracking-wide">
                SUPERCRITICAL CASCADE RUNAWAY (ρ = {currentSpectralRadius.toFixed(4)} ≥ 1.00)
              </div>
              <div className="text-xs opacity-90 font-normal">
                Order dispatch halted fail-closed · Aggressive market orders blocked · Passive limit offset widened to +{cushionBps} bps
              </div>
            </div>
          </div>
          <span className="badge badge-outline badge-sm font-mono uppercase">Lockout Active</span>
        </div>
      )}

      {/* Header */}
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
          {isLiveStreaming && (
            <span className="badge badge-success badge-outline gap-1 text-xs font-mono py-2.5 px-3">
              <Radio size={13} className="animate-pulse" /> LIVE STREAM
            </span>
          )}
          {regimeBadge(currentRegime)}
        </div>
      </div>

      <p className="text-sm text-base-content/70 leading-relaxed">
        Real-time observational telemetry modeling multivariate mutually exciting jump arrival cascades across staged candidates
        (<code className="badge badge-sm badge-neutral font-mono">BTCUSDT</code>,{' '}
        <code className="badge badge-sm badge-neutral font-mono">ETHUSDT</code>,{' '}
        <code className="badge badge-sm badge-neutral font-mono">SOLUSDT</code>). Sub-second spectral radius computation
        triggers adaptive passive limit offset cushioning and execution pacing throttling.
      </p>

      {/* Primary Fact Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 w-full">
        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Spectral Radius (ρ)</span>
            <span className="text-secondary"><Gauge size={18} /></span>
          </div>
          <div className={`font-mono text-2xl font-bold mt-1.5 ${isSupercritical ? 'text-error' : isElevated ? 'text-warning' : 'text-success'}`}>
            {currentSpectralRadius.toFixed(6)}
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
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Execution Pacing</span>
            <span className="text-warning"><Zap size={18} /></span>
          </div>
          <div className="font-mono text-2xl font-bold mt-1.5 text-warning">
            {pacingMs} <span className="text-sm font-normal text-base-content/70">ms</span>
          </div>
          <div className="text-xs text-base-content/60 mt-1">
            Dynamic inter-slice dispatch interval
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Passive Cushion</span>
            <span className="text-primary"><ShieldAlert size={18} /></span>
          </div>
          <div className="font-mono text-2xl font-bold mt-1.5 text-primary">
            +{cushionBps} <span className="text-sm font-normal text-base-content/70">bps</span>
          </div>
          <div className="text-xs text-base-content/60 mt-1">
            Adverse selection limit offset widening
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-md p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Stream Protocol</span>
            <span className="text-success"><Activity size={18} /></span>
          </div>
          <div className="font-mono text-xl font-bold mt-1.5 uppercase text-base-content">
            {isLiveStreaming ? 'WebSocket /ws' : 'REST Verified'}
          </div>
          <div className="text-xs text-success mt-1">
            {isLiveStreaming ? 'O(1) Recursive · 15s Heartbeat' : 'Cryptographic DAG verified'}
          </div>
        </div>
      </div>

      {/* Real-time Interactive Visuals: Spectral Radius Chart & Hawkes Heatmap */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <SpectralRadiusChart
            history={telemetry?.spectralRadiusHistory && telemetry.spectralRadiusHistory.length > 0 ? telemetry.spectralRadiusHistory : [model.maxSpectralRadius]}
            currentRho={currentSpectralRadius}
            isSupercritical={isSupercritical}
          />
        </div>
        <div>
          <CrossExcitationMatrix
            branchingMatrix={liveHawkes?.full_branching_matrix}
            spectralRadius={currentSpectralRadius}
          />
        </div>
      </div>

      {/* Candidates Detail Table */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
                Candidate Registry Manifest v2
              </p>
              <h3 className="text-base font-bold">Candidate Microstructure States</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              3 symbols tracked
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
                  <th className="min-w-[80px]">Pacing</th>
                  <th className="min-w-[85px]">Cushion</th>
                  <th className="min-w-[150px]">Regime / State</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map((sym) => {
                  const item = model.latestBySymbol[sym]
                  const liveJump = liveHawkes?.jump_intensity?.[sym] ?? item?.jump_intensity ?? '0.1500'
                  const liveBranch = liveHawkes?.branching_ratios?.[sym] ?? item?.branching_ratio ?? '0.2500'
                  const liveReg = liveHawkes?.regimes?.[sym] ?? item?.regime ?? 'NOMINAL'
                  const livePacing = liveHawkes?.pacing_intervals_ms?.[sym] ?? item?.pacing_interval_ms ?? 100
                  const liveCushion = liveHawkes?.limit_offset_cushions_bps?.[sym] ?? item?.limit_offset_cushion_bps ?? '0.00'
                  const liveCascade = liveHawkes?.cascade_states?.[sym] ?? item?.cascade_state ?? 'NORMAL'

                  return (
                    <tr key={sym} className="hover">
                      <td className="font-bold text-sm font-mono">{sym}</td>
                      <td className="font-mono">{liveJump}</td>
                      <td className="font-mono">{liveBranch}</td>
                      <td className="font-mono">{currentSpectralRadius.toFixed(4)}</td>
                      <td className="font-mono">{livePacing} ms</td>
                      <td className="font-mono">{liveCushion} bps</td>
                      <td>
                        <span
                          className={`badge badge-sm py-2 px-2.5 font-semibold text-[11px] whitespace-nowrap shadow-sm ${
                            liveReg.includes('SUPERCRITICAL')
                              ? 'badge-error'
                              : liveReg.includes('SEVERE')
                                ? 'badge-warning'
                                : 'badge-success'
                          }`}
                        >
                          {liveReg}: {formatCascadeState(liveCascade)}
                        </span>
                      </td>
                    </tr>
                  )
                })}
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
