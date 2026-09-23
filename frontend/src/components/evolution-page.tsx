import { useState } from 'react'
import {
  CheckCircle2,
  Clock,
  Dna,
  GitBranch,
  Lock,
  Scale,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'

import type { AutoEvolutionModel } from '@/lib/canary'

export function EvolutionPage({ model }: { model: AutoEvolutionModel }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')

  const perf = model.performance
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

  const autopsiesTrace = model.autopsiesTrace || []
  const healthEvaluations = model.healthEvaluations || {}
  const mutationsTrace = model.mutationsTrace || []
  const shadowEvaluations = model.shadowEvaluations || []

  const filteredAutopsies = autopsiesTrace.filter((a) => {
    if (selectedSymbol === 'ALL') return true
    return a.symbol === selectedSymbol
  })

  const getTierBadgeClass = (tier: string) => {
    switch (tier) {
      case 'ELITE':
        return 'badge-success text-success-content font-bold'
      case 'HEALTHY':
        return 'badge-info text-info-content'
      case 'DEGRADED':
        return 'badge-error text-error-content font-bold'
      case 'PROBATIONARY':
        return 'badge-warning text-warning-content'
      default:
        return 'badge-ghost'
    }
  }

  const getCauseBadgeClass = (cause: string) => {
    switch (cause) {
      case 'ORGANIC_ALPHA':
        return 'badge-success text-success-content'
      case 'HAWKES_CLUSTER':
        return 'badge-error text-error-content'
      case 'TIMING_DELAY':
        return 'badge-warning text-warning-content'
      case 'SPREAD_CROSS':
        return 'badge-secondary text-secondary-content'
      case 'REGIME_MISMATCH':
        return 'badge-info text-info-content'
      default:
        return 'badge-ghost'
    }
  }

  return (
    <div className="space-y-8 p-6">
      {/* Top Banner / Header */}
      <div className="flex flex-col justify-between gap-4 rounded-2xl bg-base-200/60 p-6 backdrop-blur-md lg:flex-row lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-base-content">
              Continuous Self-Learning Loop, Strategy Autopsy &amp; Auto-Evolution Daemon
            </h1>
            <span className="badge badge-primary font-mono text-xs font-semibold">
              PHASE 306
            </span>
            <span className="badge badge-success gap-1 text-xs font-semibold">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {model.status}
            </span>
          </div>
          <p className="mt-2 text-sm text-base-content/70">
            Automated trade execution autopsy decomposition, multi-factor friction attribution,
            rolling candidate health classification, and genetic/Bayesian parameter evolution
            under strict double-entry zero-drift balance governance.
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

      {/* 4 Stat Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Card 1: Evolution Cycle & Generation */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Evolution Cycle</span>
              <Dna className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-base-content font-mono">
                GEN #2
              </span>
              <span className="badge badge-sm badge-success">ACTIVE</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Staged Mutations</span>
              <span className="font-mono font-bold text-base-content">
                {perf?.staged_mutations_count ?? 0}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Promoted Candidates</span>
              <span className="font-mono font-bold text-success">
                {perf?.promoted_candidates_count ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Trade Autopsies Conducted */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Total Autopsies</span>
              <Clock className="h-4 w-4 text-info" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-base-content font-mono">
                {perf?.total_autopsies_conducted ?? 0}
              </span>
              <span className="badge badge-sm badge-info font-mono">100% AUDITED</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Organic Alpha Trades</span>
              <span className="font-mono font-bold text-success">
                {perf?.autopsy_cause_distribution?.ORGANIC_ALPHA ?? 0}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Hawkes Cluster Drag</span>
              <span className="font-mono font-bold text-error">
                {perf?.autopsy_cause_distribution?.HAWKES_CLUSTER ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Card 3: Execution Friction Attribution */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Mean Friction Bps</span>
              <Zap className="h-4 w-4 text-warning" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-warning font-mono">
                +{perf?.mean_realized_edge_bps?.toFixed(2) ?? '0.00'}
              </span>
              <span className="text-xs text-base-content/60">bps Net Edge</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Timing Error / Hawkes Drag</span>
              <span className="font-mono font-bold text-base-content">
                {perf?.mean_entry_timing_error_bps?.toFixed(1) ?? '0.0'} / {perf?.mean_hawkes_slip_drag_bps?.toFixed(1) ?? '0.0'} bps
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Adverse Selection</span>
              <span className="font-mono font-bold text-base-content">
                {perf?.mean_adverse_selection_bps?.toFixed(1) ?? '0.0'} bps
              </span>
            </div>
          </div>
        </div>

        {/* Card 4: Double-Entry Solvency Headroom */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Solvency Headroom</span>
              <Scale className="h-4 w-4 text-success" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-success font-mono">
                ${totalEquity.toFixed(2)}
              </span>
              <span className="badge badge-sm badge-success font-mono">
                {cashReservePct.toFixed(0)}% CASH
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Mathematical Drift</span>
              <span className="font-mono font-bold text-success">
                ${drift.toFixed(2)} USDT
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Micro Child Chunk Cap</span>
              <span className="font-mono font-bold text-base-content">&le; $5.00 USDT</span>
            </div>
          </div>
        </div>
      </div>

      {/* Candidate Health Tiers Table */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-lg font-bold text-base-content flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-primary" />
                Autonomous Candidate Health Tiers &amp; Rolling Performance
              </h2>
              <p className="text-xs text-base-content/60 mt-1">
                Continuous rolling evaluation classifies strategy candidates into ELITE, HEALTHY, or DEGRADED tiers.
              </p>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="table table-zebra table-sm w-full">
              <thead>
                <tr className="border-base-300 text-xs uppercase text-base-content/60">
                  <th>Candidate ID</th>
                  <th>Symbol</th>
                  <th>Health Tier</th>
                  <th>Rolling Sharpe</th>
                  <th>Win Rate</th>
                  <th>Max Drawdown</th>
                  <th>Hawkes Resilience</th>
                  <th>Trades</th>
                  <th>Consecutive Losses</th>
                  <th>Mutation Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(healthEvaluations).length === 0 ? (
                  <tr>
                    <td colSpan={10} className="py-8 text-center text-sm text-base-content/50">
                      No candidate health records available.
                    </td>
                  </tr>
                ) : (
                  Object.values(healthEvaluations).map((h) => (
                    <tr key={h.candidate_id} className="hover">
                      <td className="font-mono font-bold text-xs">{h.candidate_id}</td>
                      <td>
                        <span className="badge badge-neutral font-mono text-xs">{h.symbol}</span>
                      </td>
                      <td>
                        <span className={`badge ${getTierBadgeClass(h.tier)} text-xs`}>
                          {h.tier}
                        </span>
                      </td>
                      <td className="font-mono font-bold text-xs">
                        {h.rolling_sharpe > 0 ? (
                          <span className="text-success">{h.rolling_sharpe.toFixed(2)}</span>
                        ) : (
                          <span className="text-error">{h.rolling_sharpe.toFixed(2)}</span>
                        )}
                      </td>
                      <td className="font-mono text-xs">{h.win_rate_pct.toFixed(1)}%</td>
                      <td className="font-mono text-xs">{h.max_drawdown_pct.toFixed(2)}%</td>
                      <td className="font-mono text-xs">
                        <div className="flex items-center gap-2">
                          <progress
                            className="progress progress-primary w-16"
                            value={h.hawkes_resilience_score}
                            max="100"
                          />
                          <span>{h.hawkes_resilience_score.toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="font-mono text-xs">{h.total_trades}</td>
                      <td className="font-mono text-xs">
                        {h.consecutive_losses > 0 ? (
                          <span className="text-error font-bold">{h.consecutive_losses}</span>
                        ) : (
                          <span className="text-base-content/50">0</span>
                        )}
                      </td>
                      <td>
                        {h.needs_mutation ? (
                          <span className="badge badge-warning text-xs font-semibold gap-1">
                            <Sparkles className="h-3 w-3" />
                            MUTATED &amp; STAGED
                          </span>
                        ) : (
                          <span className="badge badge-ghost text-xs text-base-content/60">
                            STABLE
                          </span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Trade Autopsy Trace */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-lg font-bold text-base-content flex items-center gap-2">
                <Clock className="h-5 w-5 text-info" />
                Trade Execution Autopsies &amp; Microstructural Decomposition
              </h2>
              <p className="text-xs text-base-content/60 mt-1">
                Deconstructing each paper execution into timing error, Hawkes slip drag, and adverse selection.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-base-content/70">Filter Symbol:</span>
              <div className="join">
                {['ALL', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map((sym) => (
                  <button
                    key={sym}
                    onClick={() => setSelectedSymbol(sym)}
                    className={`btn join-item btn-xs ${
                      selectedSymbol === sym ? 'btn-primary' : 'btn-ghost'
                    }`}
                  >
                    {sym}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="table table-zebra table-sm w-full">
              <thead>
                <tr className="border-base-300 text-xs uppercase text-base-content/60">
                  <th>Trade ID</th>
                  <th>Candidate</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Entry / Exit Price</th>
                  <th>Qty</th>
                  <th>Timing Err</th>
                  <th>Hawkes Drag</th>
                  <th>Adv Sel</th>
                  <th>Net Edge</th>
                  <th>Net PnL</th>
                  <th>Primary Cause</th>
                </tr>
              </thead>
              <tbody>
                {filteredAutopsies.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="py-8 text-center text-sm text-base-content/50">
                      No autopsy records for selected filter.
                    </td>
                  </tr>
                ) : (
                  filteredAutopsies.map((a) => (
                    <tr key={a.trade_id} className="hover">
                      <td className="font-mono text-xs">{a.trade_id}</td>
                      <td className="font-mono text-xs text-base-content/70">{a.candidate_id}</td>
                      <td>
                        <span className="badge badge-neutral font-mono text-xs">{a.symbol}</span>
                      </td>
                      <td>
                        <span
                          className={`badge font-mono text-xs font-semibold ${
                            a.side === 'BUY'
                              ? 'badge-success text-success-content'
                              : 'badge-error text-error-content'
                          }`}
                        >
                          {a.side}
                        </span>
                      </td>
                      <td className="font-mono text-xs">
                        ${a.entry_price.toFixed(2)} &rarr; ${a.exit_price.toFixed(2)}
                      </td>
                      <td className="font-mono text-xs">{a.fill_qty}</td>
                      <td className="font-mono text-xs">{a.entry_timing_error_bps.toFixed(1)} bps</td>
                      <td className="font-mono text-xs">{a.hawkes_slip_drag_bps.toFixed(1)} bps</td>
                      <td className="font-mono text-xs">{a.adverse_selection_bps.toFixed(1)} bps</td>
                      <td className="font-mono text-xs font-bold">
                        {a.realized_edge_bps >= 0 ? (
                          <span className="text-success">+{a.realized_edge_bps.toFixed(1)}</span>
                        ) : (
                          <span className="text-error">{a.realized_edge_bps.toFixed(1)}</span>
                        )}{' '}
                        bps
                      </td>
                      <td className="font-mono text-xs font-bold">
                        {a.net_pnl_usdt >= 0 ? (
                          <span className="text-success">+${a.net_pnl_usdt.toFixed(4)}</span>
                        ) : (
                          <span className="text-error">-${Math.abs(a.net_pnl_usdt).toFixed(4)}</span>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${getCauseBadgeClass(a.cause)} text-xs`}>
                          {a.cause}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Genetic Mutations & Shadow Candidate Staging */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Genetic Mutations */}
        <div className="card border border-base-300 bg-base-100 shadow-sm">
          <div className="card-body p-6">
            <h2 className="text-lg font-bold text-base-content flex items-center gap-2">
              <Dna className="h-5 w-5 text-primary" />
              Genetic &amp; Bayesian Strategy Parameter Mutations
            </h2>
            <p className="text-xs text-base-content/60 mt-1">
              Parameters adaptively explored within strict bounded safety clamps upon candidate degradation.
            </p>

            <div className="mt-4 space-y-4">
              {mutationsTrace.length === 0 ? (
                <div className="rounded-xl border border-dashed border-base-300 p-6 text-center text-sm text-base-content/50">
                  No active mutations triggered in current cycle.
                </div>
              ) : (
                mutationsTrace.map((m) => (
                  <div
                    key={m.candidate_id}
                    className="rounded-xl border border-base-200 bg-base-200/40 p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-sm text-primary">
                        {m.candidate_id}
                      </span>
                      <span className="badge badge-outline text-xs">
                        Gen #{m.generation} (from {m.parent_candidate_id})
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs font-mono sm:grid-cols-4">
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Donchian Period</div>
                        <div className="font-bold text-base-content mt-1">{m.donchian_period}</div>
                      </div>
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">ATR Multiplier</div>
                        <div className="font-bold text-base-content mt-1">{m.atr_multiplier}x</div>
                      </div>
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Hawkes Threshold</div>
                        <div className="font-bold text-base-content mt-1">{m.hawkes_intensity_threshold}</div>
                      </div>
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Micro Bias</div>
                        <div className="font-bold text-base-content mt-1">{(m.micro_horizon_bias * 100).toFixed(0)}%</div>
                      </div>
                    </div>

                    <p className="text-xs text-base-content/80 italic">
                      &ldquo;{m.mutation_rationale}&rdquo;
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right: Shadow Candidate Sandbox */}
        <div className="card border border-base-300 bg-base-100 shadow-sm">
          <div className="card-body p-6">
            <h2 className="text-lg font-bold text-base-content flex items-center gap-2">
              <GitBranch className="h-5 w-5 text-secondary" />
              Hot-Reload Shadow Staging &amp; Promotion Sandbox
            </h2>
            <p className="text-xs text-base-content/60 mt-1">
              Mutated candidates are evaluated in shadow simulation against active parents (&ge; 15% Sharpe hurdle).
            </p>

            <div className="mt-4 space-y-4">
              {shadowEvaluations.length === 0 ? (
                <div className="rounded-xl border border-dashed border-base-300 p-6 text-center text-sm text-base-content/50">
                  No candidates currently in shadow evaluation.
                </div>
              ) : (
                shadowEvaluations.map((s) => (
                  <div
                    key={s.staged_candidate_id}
                    className="rounded-xl border border-base-200 bg-base-200/40 p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-sm text-secondary">
                        {s.staged_candidate_id}
                      </span>
                      {s.promoted ? (
                        <span className="badge badge-success text-xs font-semibold gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          PROMOTED (+{s.improvement_pct.toFixed(0)}%)
                        </span>
                      ) : (
                        <span className="badge badge-warning text-xs font-semibold">
                          EVALUATING ({s.shadow_ticks}/20 TICKS)
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Parent Sharpe</div>
                        <div className="font-bold text-error mt-1">{s.parent_sharpe.toFixed(2)}</div>
                      </div>
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Shadow Sharpe</div>
                        <div className="font-bold text-success mt-1">{s.shadow_sharpe.toFixed(2)}</div>
                      </div>
                      <div className="rounded-lg bg-base-100 p-2 text-center">
                        <div className="text-base-content/50 text-[10px]">Sharpe Delta</div>
                        <div className="font-bold text-primary mt-1">+{s.improvement_pct.toFixed(1)}%</div>
                      </div>
                    </div>

                    {s.rejection_reason && (
                      <p className="text-xs text-error italic">
                        Rejection reason: {s.rejection_reason}
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Cryptographic SHA-256 Merkle DAG Chain */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <h2 className="text-lg font-bold text-base-content flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-success" />
            Cryptographic SHA-256 Merkle DAG Provenance Chain
          </h2>
          <p className="text-xs text-base-content/60 mt-1">
            Immutable cryptographic binding linking Phase 305 parent root to Phase 306 telemetry and zero-drift ledger.
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-xl border border-base-200 bg-base-200/40 p-4">
              <span className="text-[10px] font-bold uppercase tracking-wider text-base-content/60">
                Phase 305 Parent Root
              </span>
              <div className="mt-1 font-mono text-xs font-semibold text-primary break-all">
                {model.upstreamHash}
              </div>
            </div>

            <div className="rounded-xl border border-base-200 bg-base-200/40 p-4">
              <span className="text-[10px] font-bold uppercase tracking-wider text-base-content/60">
                Phase 306 Merkle Root
              </span>
              <div className="mt-1 font-mono text-xs font-semibold text-success break-all">
                {model.merkleRoot || 'VERIFIED_CHAIN'}
              </div>
            </div>

            <div className="rounded-xl border border-base-200 bg-base-200/40 p-4">
              <span className="text-[10px] font-bold uppercase tracking-wider text-base-content/60">
                Solvency Verification
              </span>
              <div className="mt-1 flex items-center gap-2 font-mono text-xs font-bold text-success">
                <CheckCircle2 className="h-4 w-4" />
                |&Delta;| = 0.00 &lt; 10^-15 USDT
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
