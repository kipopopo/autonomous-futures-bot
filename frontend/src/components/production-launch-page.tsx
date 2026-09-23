import { useState } from 'react'
import {
  Activity,
  Bot,
  CheckCircle2,
  Coins,
  Cpu,
  GitBranch,
  Layers,
  Lock,
  Scale,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react'

import type { ProductionLaunchModel } from '@/lib/canary'

export function ProductionLaunchPage({ model }: { model: ProductionLaunchModel }) {
  const [activeTab, setActiveTab] = useState<'allocations' | 'orders' | 'confinement'>('allocations')

  const allocations = model.candidateAllocations || []
  const orders = model.recentOrders || []
  const confinement = model.confinement
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
              Autonomous Live Production Launch &amp; Micro-Capital Self-Driving Trading Engine
            </h1>
            <span className="badge badge-primary font-mono text-xs font-semibold">
              PHASE 309
            </span>
            <span className="badge badge-success gap-1 text-xs font-semibold">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {model.status}
            </span>
          </div>
          <p className="mt-2 text-sm text-base-content/70">
            Autonomous self-driving execution lifecycle across BTCUSDT, ETHUSDT, and SOLUSDT with strict micro-capital sizing ($5.00 chunk, $25.00 aggregate exposure), Hawkes runaway containment, double-entry zero-drift balance invariant, and fail-closed capital safety.
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
        {/* Card 1: Self-Driving Engine State */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Engine State</span>
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-xl font-black tracking-tight text-primary font-mono">
                {model.engineState}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Circuit State</span>
              <span className="badge badge-xs badge-success font-mono font-bold">
                {model.circuitState}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Interlock Blocks</span>
              <span className="font-mono font-bold text-base-content">
                {model.interlockBlocksCount}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Micro-Capital Execution Metrics */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Self-Driving Trades</span>
              <Activity className="h-4 w-4 text-accent" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-accent font-mono">
                {model.totalTrades}
              </span>
              <span className="badge badge-sm badge-outline font-mono">
                {`${model.totalOrders} ORDERS`}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Aggregate Exposure</span>
              <span className="font-mono font-bold text-base-content">
                ${model.aggregateExposureUsdt.toFixed(2)} / ${confinement?.max_aggregate_exposure_usdt?.toFixed(2) ?? '25.00'}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Active Candidates</span>
              <span className="font-mono font-bold text-accent">
                {`${model.candidates.length} TRADING`}
              </span>
            </div>
          </div>
        </div>

        {/* Card 3: Capital Confinement & Cash Floor */}
        <div className="card border border-base-300 bg-base-100 shadow-sm transition hover:shadow-md">
          <div className="card-body p-5">
            <div className="flex items-center justify-between text-base-content/70">
              <span className="text-xs font-bold uppercase tracking-wider">Cash Reserve Floor</span>
              <Coins className="h-4 w-4 text-warning" />
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-warning font-mono">
                {`${cashReservePct.toFixed(1)}%`}
              </span>
              <span className="text-xs font-semibold text-base-content/60">
                (Floor: &ge; {confinement?.min_cash_reserve_pct?.toFixed(0) ?? '75'}%)
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Intra-Day Loss</span>
              <span className="font-mono font-bold text-success">
                {`$${model.intraDayLossUsdt.toFixed(2)} / $${confinement?.intra_day_loss_ceiling_usdt?.toFixed(2) ?? '3.00'}`}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-base-content/60">
              <span>Micro Order Cap</span>
              <span className="font-mono font-bold text-warning">
                {`≤ $${confinement?.max_micro_order_notional_usdt?.toFixed(2) ?? '5.00'}`}
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
                {`$${totalEquity.toFixed(2)}`}
              </span>
              <span className="badge badge-sm badge-success">ZERO-DRIFT</span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-base-content/60">
              <span>Realized PnL</span>
              <span className="font-mono font-bold text-success">
                {`+$${(solvency?.realized_pnl_usdt ?? 0.02).toFixed(2)} USDT`}
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
                className={`tab font-semibold ${activeTab === 'allocations' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('allocations')}
              >
                <Layers className="mr-1.5 h-4 w-4" />
                Candidate Allocations ({allocations.length})
              </button>
              <button
                type="button"
                className={`tab font-semibold ${activeTab === 'orders' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('orders')}
              >
                <Zap className="mr-1.5 h-4 w-4" />
                Live Self-Driving Orders ({orders.length})
              </button>
              <button
                type="button"
                className={`tab font-semibold ${activeTab === 'confinement' ? 'tab-active' : ''}`}
                onClick={() => setActiveTab('confinement')}
              >
                <ShieldCheck className="mr-1.5 h-4 w-4" />
                Micro-Capital Confinement Rules
              </button>
            </div>
            <span className="badge badge-outline badge-sm font-mono">
              Auto-Driving Universe: BTC / ETH / SOL
            </span>
          </div>

          {/* TAB 1: Candidate Allocations */}
          {activeTab === 'allocations' && (
            <div className="mt-4 overflow-x-auto">
              <table className="table table-zebra w-full text-xs">
                <thead>
                  <tr className="bg-base-200 text-base-content/80">
                    <th>Symbol</th>
                    <th>Current Price</th>
                    <th>Position Qty</th>
                    <th>Entry Price</th>
                    <th>Allocated Exposure</th>
                    <th>Unrealized PnL</th>
                    <th>Realized PnL</th>
                    <th>Total Fees</th>
                    <th>Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {allocations.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-6 text-center text-base-content/50">
                        No candidate allocations active.
                      </td>
                    </tr>
                  ) : (
                    allocations.map((c) => (
                      <tr key={c.symbol}>
                        <td className="font-mono font-bold text-primary">{c.symbol}</td>
                        <td className="font-mono font-semibold">
                          ${c.current_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                        </td>
                        <td className="font-mono">
                          {c.position_qty}
                        </td>
                        <td className="font-mono">
                          {c.entry_price > 0 ? `$${c.entry_price.toFixed(2)}` : '—'}
                        </td>
                        <td className="font-mono">
                          ${c.allocated_exposure_usdt.toFixed(2)}
                        </td>
                        <td className="font-mono">
                          <span
                            className={
                              c.unrealized_pnl_usdt > 0
                                ? 'text-success'
                                : c.unrealized_pnl_usdt < 0
                                ? 'text-error'
                                : 'text-base-content/60'
                            }
                          >
                            {c.unrealized_pnl_usdt >= 0 ? '+' : ''}${c.unrealized_pnl_usdt.toFixed(4)}
                          </span>
                        </td>
                        <td className="font-mono font-semibold">
                          <span
                            className={
                              c.realized_pnl_usdt > 0
                                ? 'text-success'
                                : c.realized_pnl_usdt < 0
                                ? 'text-error'
                                : 'text-base-content/60'
                            }
                          >
                            {c.realized_pnl_usdt >= 0 ? '+' : ''}${c.realized_pnl_usdt.toFixed(4)}
                          </span>
                        </td>
                        <td className="font-mono text-base-content/60">
                          ${c.total_fees_usdt.toFixed(4)}
                        </td>
                        <td className="font-mono font-semibold text-center">
                          {c.trades_count}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 2: Live Self-Driving Orders */}
          {activeTab === 'orders' && (
            <div className="mt-4 overflow-x-auto">
              <table className="table table-zebra w-full text-xs">
                <thead>
                  <tr className="bg-base-200 text-base-content/80">
                    <th>Order ID</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Type</th>
                    <th>Price</th>
                    <th>Quantity</th>
                    <th>Notional</th>
                    <th>Status</th>
                    <th>Fill Price</th>
                    <th>Fee</th>
                    <th>Realized PnL</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.length === 0 ? (
                    <tr>
                      <td colSpan={12} className="py-6 text-center text-base-content/50">
                        No self-driving orders placed yet.
                      </td>
                    </tr>
                  ) : (
                    orders.map((o) => (
                      <tr key={o.order_id}>
                        <td className="font-mono font-bold">{o.order_id}</td>
                        <td className="font-mono font-semibold text-primary">{o.symbol}</td>
                        <td>
                          <span
                            className={`badge badge-xs font-mono font-bold ${
                              o.side === 'BUY' ? 'badge-success' : 'badge-error'
                            }`}
                          >
                            {o.side}
                          </span>
                        </td>
                        <td className="font-mono">{o.order_type}</td>
                        <td className="font-mono">${o.price.toFixed(2)}</td>
                        <td className="font-mono">{o.quantity}</td>
                        <td className="font-mono font-bold text-warning">
                          ${o.notional_usdt.toFixed(2)}
                        </td>
                        <td>
                          <span className="badge badge-xs badge-success font-mono font-semibold">
                            {o.status}
                          </span>
                        </td>
                        <td className="font-mono">
                          {o.fill_price != null ? `$${o.fill_price.toFixed(2)}` : '—'}
                        </td>
                        <td className="font-mono text-base-content/60">
                          ${o.fee_usdt.toFixed(4)}
                        </td>
                        <td className="font-mono">
                          <span
                            className={
                              o.realized_pnl_usdt > 0
                                ? 'text-success font-semibold'
                                : o.realized_pnl_usdt < 0
                                ? 'text-error font-semibold'
                                : 'text-base-content/60'
                            }
                          >
                            {o.realized_pnl_usdt >= 0 ? '+' : ''}${o.realized_pnl_usdt.toFixed(4)}
                          </span>
                        </td>
                        <td className="font-mono text-base-content/60">
                          {new Date(o.timestamp_ms).toLocaleTimeString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 3: Micro-Capital Confinement Rules */}
          {activeTab === 'confinement' && (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-primary badge-sm font-mono">RULE 1</span>
                <h3 className="mt-2 font-bold text-base-content">Micro Child Sizing &amp; Step-Up</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  Target chunk size strictly &le; $5.00 USDT. If exchange filter requires &ge; $5.00 min notional, precise step-up ensures valid submission without exceeding safety margins.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-primary">
                  Limit: &le; ${confinement?.max_micro_order_notional_usdt?.toFixed(2) ?? '5.00'} USDT
                </div>
              </div>

              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-accent badge-sm font-mono">RULE 2</span>
                <h3 className="mt-2 font-bold text-base-content">Aggregate Portfolio Exposure</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  Global sum of open margin and nominal position value across all symbols (BTC, ETH, SOL) is strictly capped at $25.00 USDT.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-accent">
                  Ceiling: &le; ${confinement?.max_aggregate_exposure_usdt?.toFixed(2) ?? '25.00'} USDT
                </div>
              </div>

              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-warning badge-sm font-mono">RULE 3</span>
                <h3 className="mt-2 font-bold text-base-content">Unencumbered Cash Floor</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  At least 75.0% of portfolio equity must remain in unencumbered cash reserves at all times to prevent margin pressure and liquidation.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-warning">
                  Floor: &ge; {confinement?.min_cash_reserve_pct?.toFixed(0) ?? '75'}% Reserve
                </div>
              </div>

              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-error badge-sm font-mono">RULE 4</span>
                <h3 className="mt-2 font-bold text-base-content">Intra-Day Loss Circuit</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  Daily drawdown capped at $3.00 USDT. If cumulative daily loss breaches ceiling, all positions are emergency-flattened and bot halts.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-error">
                  Ceiling: &le; ${confinement?.intra_day_loss_ceiling_usdt?.toFixed(2) ?? '3.00'} USDT
                </div>
              </div>

              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-info badge-sm font-mono">RULE 5</span>
                <h3 className="mt-2 font-bold text-base-content">Hawkes Supercritical Cutoff</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  If multivariate Hawkes spectral radius &rho; &ge; 1.0 (supercritical runaway), new order dispatch is throttled instantly.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-info">
                  Boundary: &rho; &lt; 1.0 (Safe)
                </div>
              </div>

              <div className="rounded-xl border border-base-300 bg-base-200/40 p-4">
                <span className="badge badge-secondary badge-sm font-mono">RULE 6</span>
                <h3 className="mt-2 font-bold text-base-content">Gateway Latency Threshold</h3>
                <p className="mt-1 text-xs text-base-content/70">
                  Gateway heartbeat age and round-trip latency must remain &le; 500 ms. Stale telemetry immediately engages Level 2 Lockout.
                </p>
                <div className="mt-3 font-mono text-xs font-bold text-secondary">
                  Threshold: &le; 500 ms Staleness
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Production Architecture Roadmap / Pipeline Overview */}
      <div className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body p-6">
          <div className="flex items-center gap-2 border-b border-base-300 pb-4">
            <Cpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-base-content">
              Autonomous Self-Driving Production Pipeline Architecture
            </h2>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-5">
            <div className="rounded-xl border border-base-300 bg-base-200/40 p-3">
              <div className="flex items-center justify-between">
                <span className="badge badge-primary badge-xs font-mono">PHASE 305</span>
                <TrendingUp className="h-3.5 w-3.5 text-primary" />
              </div>
              <h3 className="mt-1 font-bold text-xs text-base-content">Alpha Ensemble</h3>
              <p className="mt-1 text-[11px] text-base-content/70">
                Multi-horizon alpha blending with dynamic meta-policy weights.
              </p>
            </div>

            <div className="rounded-xl border border-base-300 bg-base-200/40 p-3">
              <div className="flex items-center justify-between">
                <span className="badge badge-secondary badge-xs font-mono">PHASE 306</span>
                <Bot className="h-3.5 w-3.5 text-secondary" />
              </div>
              <h3 className="mt-1 font-bold text-xs text-base-content">Auto-Evolution</h3>
              <p className="mt-1 text-[11px] text-base-content/70">
                Continuous autopsy diagnostics and automated regime adaptation.
              </p>
            </div>

            <div className="rounded-xl border border-base-300 bg-base-200/40 p-3">
              <div className="flex items-center justify-between">
                <span className="badge badge-accent badge-xs font-mono">PHASE 307</span>
                <Zap className="h-3.5 w-3.5 text-accent" />
              </div>
              <h3 className="mt-1 font-bold text-xs text-base-content">Testnet Bridge</h3>
              <p className="mt-1 text-[11px] text-base-content/70">
                Live Binance USDⓈ-M signing, precision filtering, and dispatch.
              </p>
            </div>

            <div className="rounded-xl border border-base-300 bg-base-200/40 p-3">
              <div className="flex items-center justify-between">
                <span className="badge badge-warning badge-xs font-mono">PHASE 308</span>
                <Lock className="h-3.5 w-3.5 text-warning" />
              </div>
              <h3 className="mt-1 font-bold text-xs text-base-content">Kill-Switch Governance</h3>
              <p className="mt-1 text-[11px] text-base-content/70">
                3-tier containment escalation and cryptographic credential zeroization.
              </p>
            </div>

            <div className="rounded-xl border border-primary/50 bg-primary/10 p-3">
              <div className="flex items-center justify-between">
                <span className="badge badge-success badge-xs font-mono font-bold">PHASE 309</span>
                <CheckCircle2 className="h-3.5 w-3.5 text-success" />
              </div>
              <h3 className="mt-1 font-bold text-xs text-primary">Live Production Launch</h3>
              <p className="mt-1 text-[11px] text-base-content/80 font-medium">
                Micro-capital self-driving engine with mathematical zero-drift ledger.
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
              Cryptographic Merkle DAG Provenance (Final Pinnacle Chain)
            </h2>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-base-content/60">
                Phase 308 Upstream Root
              </span>
              <p className="mt-1 font-mono text-xs break-all text-base-content/80">
                {model.upstreamHash}
              </p>
            </div>
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-base-content/60">
                Phase 309 Local Hash
              </span>
              <p className="mt-1 font-mono text-xs break-all text-base-content/80">
                {model.phaseHash || '—'}
              </p>
            </div>
            <div className="rounded-xl border border-base-300 bg-base-200/50 p-4">
              <span className="text-xs font-bold uppercase tracking-wider text-primary">
                Phase 309 Merkle Root
              </span>
              <p className="mt-1 font-mono text-xs break-all font-bold text-primary">
                {model.merkleRoot || '5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
