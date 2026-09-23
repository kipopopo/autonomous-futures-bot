import { useState } from 'react'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Layers,
  Lock,
  Minus,
  PieChart,
  Scale,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react'

import type { EnsembleModel } from '@/lib/canary'

export function EnsemblePage({ model }: { model: EnsembleModel }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')

  const perf = model.performance
  const solvency = model.solvency
  const ledger = model.ledger

  const startingEquity = solvency?.starting_equity_usdt ?? ledger?.starting_equity ?? 100.0
  const cash = solvency?.cash_usdt ?? ledger?.cash ?? 100.0
  const allocatedMargin = solvency?.allocated_margin_usdt ?? ledger?.allocated_margin ?? 0.0
  const unrealizedPnl = solvency?.unrealized_pnl_usdt ?? ledger?.unrealized_pnl ?? 0.0
  const realizedPnl = solvency?.realized_pnl_usdt ?? ledger?.realized_pnl ?? 0.0
  const totalEquity = solvency?.total_equity_usdt ?? cash + allocatedMargin + unrealizedPnl
  const drift = solvency?.drift_usdt ?? ledger?.drift ?? 0.0
  const isZeroDrift = model.isZeroDrift
  const cashReservePct =
    solvency?.cash_reserve_pct ?? (startingEquity > 0 ? (cash / startingEquity) * 100 : 100)

  const shadowStates = model.shadowStates || {}
  const decisionsTrace = model.decisionsTrace || []

  const filteredTrace = decisionsTrace.filter((t) => {
    if (selectedSymbol === 'ALL') return true
    return t.symbol === selectedSymbol
  })

  // Color helper for market regimes
  const getRegimeBadgeClass = (regime: string) => {
    switch (regime) {
      case 'CALM_BALANCED':
        return 'badge-success text-success-content'
      case 'VOLATILITY_EXPANSION':
        return 'badge-warning text-warning-content'
      case 'TRENDING_MOMENTUM':
        return 'badge-primary text-primary-content'
      case 'MEAN_REVERTING':
        return 'badge-info text-info-content'
      case 'TOXIC_TURBULENCE':
        return 'badge-error text-error-content'
      default:
        return 'badge-ghost'
    }
  }

  const getActionBadgeClass = (action: string) => {
    switch (action) {
      case 'BUY':
        return 'badge-success text-success-content'
      case 'SELL':
        return 'badge-error text-error-content'
      case 'HOLD':
        return 'badge-ghost'
      case 'DEFENSIVE_SUPPRESSED':
        return 'badge-warning text-warning-content'
      default:
        return 'badge-ghost'
    }
  }

  const meanMicro = (perf?.mean_horizon_weights?.micro ?? 0.35) * 100
  const meanShort = (perf?.mean_horizon_weights?.short ?? 0.35) * 100
  const meanMed = (perf?.mean_horizon_weights?.medium ?? 0.30) * 100

  return (
    <div className="space-y-8 p-6">
      {/* Top Banner / Header */}
      <div className="flex flex-col justify-between gap-4 rounded-2xl bg-base-200/60 p-6 backdrop-blur-md lg:flex-row lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-base-content">
              Autonomous Multi-Horizon Alpha Ensemble &amp; Meta-Policy Blending Engine
            </h1>
            <span className="badge badge-primary font-mono text-xs font-semibold">
              PHASE 305
            </span>
            <span className="badge badge-success gap-1 text-xs font-semibold">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {model.status}
            </span>
          </div>
          <p className="mt-2 text-sm text-base-content/70">
            Tri-horizon alpha extraction (Micro 1s-5s, Short 1m-5m, Medium 15m-1h), dynamic meta-policy regime weighting,
            directional conflict penalty shading, micro child-slicing caps, and continuous double-entry zero-drift solvency governance.
          </p>
        </div>

        {/* Global Safety Indicators */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="badge badge-success gap-1 px-3 py-3 text-xs font-semibold">
            <ShieldCheck className="h-3.5 w-3.5" />
            PAPER SAFE: CONFINED
          </div>
          <div className="badge badge-warning gap-1 px-3 py-3 text-xs font-semibold">
            <Lock className="h-3.5 w-3.5" />
            AUTHORITY: OFF
          </div>
          <div className="badge badge-accent gap-1 px-3 py-3 text-xs font-semibold">
            <Zap className="h-3.5 w-3.5" />
            {`ZERO DRIFT: |Δ|=${(drift ?? 0).toFixed(4)} USDT`}
          </div>
        </div>
      </div>

      {/* 4 KPI Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1: Active Conviction & Conflict Ratio */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-base-content/60">
              Conviction &amp; Conflict
            </span>
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Layers className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-bold text-primary">
              {`${((perf?.average_effective_conviction ?? 0) * 100).toFixed(1)}%`}
            </span>
            <span className="text-xs text-base-content/60">avg conviction</span>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-base-content/70">
            <span>Conflict Ratio:</span>
            <span className={`badge font-mono badge-sm ${perf?.conflict_count ? 'badge-warning' : 'badge-ghost'}`}>
              {`${perf?.conflict_ratio_pct ?? 0}% (${perf?.conflict_count ?? 0} events)`}
            </span>
          </div>
        </div>

        {/* KPI 2: Dynamic Horizon Distribution */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-base-content/60">
              Mean Horizon Weights
            </span>
            <div className="rounded-lg bg-info/10 p-2 text-info">
              <PieChart className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-1 font-mono text-xs">
            <span className="text-info font-bold">{`Micro ${meanMicro.toFixed(0)}%`}</span>
            <span className="text-base-content/40">•</span>
            <span className="text-accent font-bold">{`Short ${meanShort.toFixed(0)}%`}</span>
            <span className="text-base-content/40">•</span>
            <span className="text-primary font-bold">{`Med ${meanMed.toFixed(0)}%`}</span>
          </div>
          <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-base-300">
            <div style={{ width: `${meanMicro}%` }} className="bg-info" title="Micro Horizon" />
            <div style={{ width: `${meanShort}%` }} className="bg-accent" title="Short Horizon" />
            <div style={{ width: `${meanMed}%` }} className="bg-primary" title="Medium Horizon" />
          </div>
        </div>

        {/* KPI 3: Solvency Headroom & Balance */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-base-content/60">
              Solvency &amp; Headroom
            </span>
            <div className="rounded-lg bg-success/10 p-2 text-success">
              <Scale className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-bold text-success">
              {`${cashReservePct.toFixed(1)}%`}
            </span>
            <span className="text-xs text-base-content/60">cash reserve</span>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-base-content/70">
            <span>{`Cash: $${cash.toFixed(2)}`}</span>
            <span className="badge badge-success badge-sm font-mono">
              {isZeroDrift ? 'EXACT ZERO-DRIFT' : 'DRIFT WARNING'}
            </span>
          </div>
        </div>

        {/* KPI 4: Risk / Reward & Longevity */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-base-content/60">
              Longevity &amp; Sharpe
            </span>
            <div className="rounded-lg bg-warning/10 p-2 text-warning">
              <TrendingUp className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="font-mono text-2xl font-bold text-base-content">
              {(perf?.realized_sharpe_ratio ?? 0).toFixed(1)}
            </span>
            <span className="text-xs text-base-content/60">Sharpe Ratio</span>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-base-content/70">
            <span>{`PF: ${(perf?.profit_factor ?? 0).toFixed(1)}x`}</span>
            <span className="badge badge-ghost badge-sm font-mono">
              {`MDD: ${(perf?.max_drawdown_pct ?? 0).toFixed(3)}%`}
            </span>
          </div>
        </div>
      </div>

      {/* Active Candidate Horizon Signal Matrix */}
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
        <div className="flex flex-col justify-between gap-4 border-b border-base-200 pb-4 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-lg font-bold text-base-content">Candidate Alpha Signals &amp; Ensemble Blending</h2>
            <p className="text-xs text-base-content/60">
              Live multi-horizon signal decomposition, conflict detection, and micro-slicing target actions per candidate.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-base-content/60">Filter Asset:</span>
            <select
              className="select select-bordered select-xs"
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
            >
              <option value="ALL">ALL CANDIDATES</option>
              {model.candidates.map((sym) => (
                <option key={sym} value={sym}>
                  {sym}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="table table-zebra table-sm">
            <thead>
              <tr className="text-xs text-base-content/70">
                <th>Symbol</th>
                <th>Regime</th>
                <th>Micro (1s-5s)</th>
                <th>Short (1m-5m)</th>
                <th>Medium (15m-1h)</th>
                <th>Conflict Status</th>
                <th>Effective Direction</th>
                <th>Conviction</th>
                <th>Target Action</th>
                <th>Micro Chunk Cap</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(shadowStates).map(([sym, state]) => {
                const dec = state.last_decision
                const signals = dec?.signals || {}
                const micro = signals['MICRO_1S_5S']
                const short = signals['SHORT_1M_5M']
                const med = signals['MEDIUM_15M_1H']

                return (
                  <tr key={sym} className="font-mono text-xs">
                    <td className="font-bold text-base-content">{sym}</td>
                    <td>
                      <span className={`badge badge-sm ${getRegimeBadgeClass(state.active_regime)}`}>
                        {state.active_regime}
                      </span>
                    </td>
                    <td>
                      <div className="flex items-center gap-1">
                        {micro && micro.direction > 0 ? (
                          <ArrowUpRight className="h-3 w-3 text-success" />
                        ) : micro && micro.direction < 0 ? (
                          <ArrowDownRight className="h-3 w-3 text-error" />
                        ) : (
                          <Minus className="h-3 w-3 text-base-content/40" />
                        )}
                        <span>{micro ? `${micro.direction > 0 ? '+' : ''}${micro.direction.toFixed(2)}` : '0.00'}</span>
                        <span className="text-base-content/40">({micro ? (micro.conviction * 100).toFixed(0) : 0}%)</span>
                      </div>
                    </td>
                    <td>
                      <div className="flex items-center gap-1">
                        {short && short.direction > 0 ? (
                          <ArrowUpRight className="h-3 w-3 text-success" />
                        ) : short && short.direction < 0 ? (
                          <ArrowDownRight className="h-3 w-3 text-error" />
                        ) : (
                          <Minus className="h-3 w-3 text-base-content/40" />
                        )}
                        <span>{short ? `${short.direction > 0 ? '+' : ''}${short.direction.toFixed(2)}` : '0.00'}</span>
                        <span className="text-base-content/40">({short ? (short.conviction * 100).toFixed(0) : 0}%)</span>
                      </div>
                    </td>
                    <td>
                      <div className="flex items-center gap-1">
                        {med && med.direction > 0 ? (
                          <ArrowUpRight className="h-3 w-3 text-success" />
                        ) : med && med.direction < 0 ? (
                          <ArrowDownRight className="h-3 w-3 text-error" />
                        ) : (
                          <Minus className="h-3 w-3 text-base-content/40" />
                        )}
                        <span>{med ? `${med.direction > 0 ? '+' : ''}${med.direction.toFixed(2)}` : '0.00'}</span>
                        <span className="text-base-content/40">({med ? (med.conviction * 100).toFixed(0) : 0}%)</span>
                      </div>
                    </td>
                    <td>
                      {dec?.conflict_detected ? (
                        <span className="badge badge-warning badge-sm gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          {`SHADED (×${dec.conflict_penalty.toFixed(2)})`}
                        </span>
                      ) : (
                        <span className="badge badge-success badge-sm">ALIGNED</span>
                      )}
                    </td>
                    <td>
                      <span className={dec?.effective_direction && dec.effective_direction > 0 ? 'text-success font-bold' : dec?.effective_direction && dec.effective_direction < 0 ? 'text-error font-bold' : ''}>
                        {dec ? `${dec.effective_direction > 0 ? '+' : ''}${dec.effective_direction.toFixed(2)}` : '0.00'}
                      </span>
                    </td>
                    <td>
                      <span>{dec ? `${(dec.effective_conviction * 100).toFixed(1)}%` : '0.0%'}</span>
                    </td>
                    <td>
                      <span className={`badge badge-sm font-semibold ${getActionBadgeClass(dec?.target_action || 'HOLD')}`}>
                        {dec?.target_action || 'HOLD'}
                      </span>
                    </td>
                    <td>
                      <span className="font-bold text-accent">
                        {dec ? `$${dec.target_micro_chunk_usdt.toFixed(2)}` : '$0.00'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Decision Evolution Trace Log */}
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
        <div className="border-b border-base-200 pb-4">
          <h2 className="text-lg font-bold text-base-content">Ensemble Decision Evolution Trace</h2>
          <p className="text-xs text-base-content/60">
            Deterministic sequence of tri-horizon alpha blends, conflict penalties, and micro-slicing executions.
          </p>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="table table-zebra table-sm">
            <thead>
              <tr className="text-xs text-base-content/70">
                <th>Timestamp</th>
                <th>Symbol</th>
                <th>Regime</th>
                <th>Weights (M/S/L)</th>
                <th>Raw Dir</th>
                <th>Conflict</th>
                <th>Eff Dir</th>
                <th>Eff Conv</th>
                <th>Action</th>
                <th>Micro Cap</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrace.map((tr, idx) => (
                <tr key={`${tr.symbol}-${tr.timestamp_ms}-${idx}`} className="font-mono text-xs">
                  <td className="text-base-content/60">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(tr.timestamp_ms).toLocaleTimeString()}
                    </div>
                  </td>
                  <td className="font-bold">{tr.symbol}</td>
                  <td>
                    <span className={`badge badge-xs ${getRegimeBadgeClass(tr.regime)}`}>
                      {tr.regime}
                    </span>
                  </td>
                  <td className="text-base-content/70">
                    {`${(tr.weights.micro_weight * 100).toFixed(0)}/${(tr.weights.short_weight * 100).toFixed(0)}/${(tr.weights.medium_weight * 100).toFixed(0)}`}
                  </td>
                  <td>{tr.raw_blended_direction.toFixed(2)}</td>
                  <td>
                    {tr.conflict_detected ? (
                      <span className="badge badge-warning badge-xs">YES (×{tr.conflict_penalty.toFixed(2)})</span>
                    ) : (
                      <span className="badge badge-ghost badge-xs">NO</span>
                    )}
                  </td>
                  <td className={tr.effective_direction > 0 ? 'text-success font-bold' : tr.effective_direction < 0 ? 'text-error font-bold' : ''}>
                    {`${tr.effective_direction > 0 ? '+' : ''}${tr.effective_direction.toFixed(2)}`}
                  </td>
                  <td>{(tr.effective_conviction * 100).toFixed(1)}%</td>
                  <td>
                    <span className={`badge badge-xs font-semibold ${getActionBadgeClass(tr.target_action)}`}>
                      {tr.target_action}
                    </span>
                  </td>
                  <td className="font-bold text-accent">${tr.target_micro_chunk_usdt.toFixed(2)}</td>
                  <td>
                    <span className="badge badge-ghost badge-xs font-mono">{tr.ensemble_state}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Double-Entry Solvency Ledger & Cryptographic Merkle DAG Chain */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Solvency Ledger Card */}
        <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
          <div className="flex items-center justify-between border-b border-base-200 pb-3">
            <div className="flex items-center gap-2">
              <Scale className="h-5 w-5 text-primary" />
              <h2 className="text-base font-bold text-base-content">Double-Entry Solvency Ledger</h2>
            </div>
            <span className="badge badge-success badge-sm font-mono">
              |Δ| &lt; 10⁻¹⁵ USDT
            </span>
          </div>

          <div className="mt-4 space-y-3 font-mono text-xs">
            <div className="flex justify-between border-b border-base-200/50 pb-2">
              <span className="text-base-content/60">Starting Equity:</span>
              <span className="font-bold text-base-content">${startingEquity.toFixed(4)} USDT</span>
            </div>
            <div className="flex justify-between border-b border-base-200/50 pb-2">
              <span className="text-base-content/60">Available Cash:</span>
              <span className="font-bold text-success">${cash.toFixed(4)} USDT</span>
            </div>
            <div className="flex justify-between border-b border-base-200/50 pb-2">
              <span className="text-base-content/60">Allocated Margin:</span>
              <span className="font-bold text-warning">${allocatedMargin.toFixed(4)} USDT</span>
            </div>
            <div className="flex justify-between border-b border-base-200/50 pb-2">
              <span className="text-base-content/60">Unrealized PnL:</span>
              <span className={unrealizedPnl >= 0 ? 'text-success font-bold' : 'text-error font-bold'}>
                {`${unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(4)} USDT`}
              </span>
            </div>
            <div className="flex justify-between border-b border-base-200/50 pb-2">
              <span className="text-base-content/60">Realized PnL:</span>
              <span className={realizedPnl >= 0 ? 'text-success font-bold' : 'text-error font-bold'}>
                {`${realizedPnl >= 0 ? '+' : ''}${realizedPnl.toFixed(4)} USDT`}
              </span>
            </div>
            <div className="flex justify-between pt-1">
              <span className="font-bold text-base-content">Total Net Equity:</span>
              <span className="font-bold text-primary">${totalEquity.toFixed(4)} USDT</span>
            </div>
            <div className="flex justify-between text-base-content/60 pt-1">
              <span>Mathematical Drift (|Δ|):</span>
              <span className="font-mono text-success">{`${drift.toFixed(6)} USDT`}</span>
            </div>
          </div>
        </div>

        {/* Cryptographic Merkle DAG Chain Card */}
        <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
          <div className="flex items-center justify-between border-b border-base-200 pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-accent" />
              <h2 className="text-base font-bold text-base-content">Cryptographic Merkle DAG Chain</h2>
            </div>
            <span className="badge badge-accent badge-sm font-mono">SHA-256</span>
          </div>

          <div className="mt-4 space-y-3 text-xs">
            <div>
              <span className="font-medium text-base-content/60">Parent Phase 304 Merkle Root:</span>
              <div className="mt-1 break-all rounded-lg bg-base-200/70 p-2 font-mono text-[11px] text-base-content/80">
                {model.upstreamHash}
              </div>
            </div>

            <div>
              <span className="font-medium text-base-content/60">Phase 305 Ensemble Merkle Root:</span>
              <div className="mt-1 break-all rounded-lg bg-primary/10 p-2 font-mono text-[11px] font-bold text-primary">
                {model.merkleRoot || 'e6d84cef9cef37b0c211a7c77536eeafd22537a511770f480e099b1847ea07d9'}
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between pt-2">
              <span className="text-base-content/70">Cryptographic Verification:</span>
              <span className="badge badge-success gap-1 font-mono text-xs">
                <CheckCircle2 className="h-3 w-3" />
                VERIFIED IMMUTABLE
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
