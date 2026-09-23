import { useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Lock,
  Scale,
  Shield,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  Zap,
} from 'lucide-react'

import type { ExecutionGuardModel } from '@/lib/canary'

export function ExecutionGuardPage({ model }: { model: ExecutionGuardModel }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')

  const startingEquity =
    model.solvency?.starting_equity_usdt ?? model.ledger?.starting_equity ?? 100.0
  const cash = model.solvency?.cash_usdt ?? model.ledger?.cash ?? 100.0
  const allocatedMargin =
    model.solvency?.allocated_margin_usdt ?? model.ledger?.allocated_margin ?? 0.0
  const unrealizedPnl =
    model.solvency?.unrealized_pnl_usdt ?? model.ledger?.unrealized_pnl ?? 0.0
  const realizedPnl =
    model.solvency?.realized_pnl_usdt ?? model.ledger?.realized_pnl ?? 0.0
  const totalEquity =
    model.solvency?.total_equity_usdt ?? cash + allocatedMargin + unrealizedPnl
  const drift = model.solvency?.drift_usdt ?? model.ledger?.drift ?? 0.0
  const isZeroDrift = model.isZeroDrift
  const cashReservePct =
    model.solvency?.cash_reserve_pct ??
    (startingEquity > 0 ? (cash / startingEquity) * 100 : 100)

  const toxicityMetrics = model.toxicityMetrics || []
  const shadedQuotes = model.shadedQuotes || []
  const slippageDecompositions = model.slippageDecompositions || []
  const childOrders = model.childOrders || []

  const filteredDecompositions = slippageDecompositions.filter((d) => {
    if (selectedSymbol === 'ALL') return true
    return d.symbol === selectedSymbol
  })

  const filteredQuotes = shadedQuotes.filter((q) => {
    if (selectedSymbol === 'ALL') return true
    return q.symbol === selectedSymbol
  })

  return (
    <div className="space-y-8 p-6">
      {/* Top Banner / Header */}
      <div className="flex flex-col justify-between gap-4 rounded-2xl bg-base-200/60 p-6 backdrop-blur-md lg:flex-row lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-base-content">
              Adverse Selection Guard &amp; Microstructure Slippage Attribution
            </h1>
            <span className="badge badge-primary font-mono text-xs font-semibold">
              PHASE 302
            </span>
            <span className="badge badge-success gap-1 text-xs">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {model.status}
            </span>
            <span className="badge badge-outline text-xs">
              {`CIRCUIT: ${model.circuitState}`}
            </span>
          </div>
          <p className="mt-2 text-sm text-base-content/70">
            Real-time VPIN toxicity monitoring, Avellaneda-Stoikov reservation quote shading with
            Hawkes jump hazard cushions, fail-closed quote pull defense, and 4-component causal
            slippage attribution.
          </p>
        </div>

        {/* Global Safety Indicators */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="badge badge-success gap-1 px-3 py-3 text-xs font-semibold">
            <ShieldCheck className="h-3.5 w-3.5" />
            PAPER SAFE: VERIFIED
          </div>
          <div className="badge badge-warning gap-1 px-3 py-3 text-xs font-semibold">
            <Lock className="h-3.5 w-3.5" />
            AUTHORITY: OFF
          </div>
          <div className="badge badge-accent gap-1 px-3 py-3 text-xs font-semibold">
            <Zap className="h-3.5 w-3.5" />
            {`ZERO DRIFT: ${drift.toFixed(2)} USDT`}
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1: Toxicity & Adverse Selection */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between text-base-content/70">
            <span className="text-xs font-semibold uppercase tracking-wider">
              Order Flow Toxicity
            </span>
            <ShieldAlert className="h-4 w-4 text-warning" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-base-content">
              {model.anyQuotesPulled ? 'DEFENSE ACTIVE' : 'NOMINAL FLOW'}
            </span>
          </div>
          <p className="mt-1 text-xs text-base-content/60">
            {`${toxicityMetrics.filter((m) => m.quotes_pulled).length} / ${toxicityMetrics.length} symbols pulled quotes`}
          </p>
        </div>

        {/* KPI 2: Reservation Price Cushion */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between text-base-content/70">
            <span className="text-xs font-semibold uppercase tracking-wider">
              Avellaneda-Stoikov
            </span>
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-base-content">
              {`${(toxicityMetrics[0]?.shading_offset_bps ?? 25.0).toFixed(1)} bps`}
            </span>
            <span className="text-xs font-medium text-info">Hawkes Cushion</span>
          </div>
          <p className="mt-1 text-xs text-base-content/60">
            Inventory penalty &amp; jump hazard spread expansion
          </p>
        </div>

        {/* KPI 3: Slippage Attribution */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between text-base-content/70">
            <span className="text-xs font-semibold uppercase tracking-wider">
              Mean Realized Slippage
            </span>
            <TrendingDown className="h-4 w-4 text-success" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-base-content">
              {`${model.meanSlippageBps.toFixed(2)} bps`}
            </span>
            <span className="badge badge-success badge-sm text-[10px]">
              {model.allWithinTolerance ? 'WITHIN TOLERANCE' : 'BREACH'}
            </span>
          </div>
          <p className="mt-1 text-xs text-base-content/60">
            {`Max: ${model.maxSlippageBps.toFixed(2)} bps (≤ 5.0 maker / ≤ 15.0 taker)`}
          </p>
        </div>

        {/* KPI 4: Solvency & Cash Reserve */}
        <div className="rounded-xl border border-base-300 bg-base-100 p-5 shadow-sm">
          <div className="flex items-center justify-between text-base-content/70">
            <span className="text-xs font-semibold uppercase tracking-wider">
              Unencumbered Cash
            </span>
            <Scale className="h-4 w-4 text-accent" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-base-content">
              {`${cashReservePct.toFixed(1)}%`}
            </span>
            <span className="text-xs font-medium text-success">Floor ≥ 40.0%</span>
          </div>
          <p className="mt-1 text-xs text-base-content/60">
            {`Cash: ${cash.toFixed(2)} USDT / Equity: ${totalEquity.toFixed(2)} USDT`}
          </p>
        </div>
      </div>

      {/* Symbol Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-base-300 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-base-content/60">
            Filter by Asset:
          </span>
          {['ALL', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map((sym) => (
            <button
              key={sym}
              type="button"
              className={`btn btn-xs rounded-lg ${
                selectedSymbol === sym ? 'btn-primary' : 'btn-ghost'
              }`}
              onClick={() => setSelectedSymbol(sym)}
            >
              {sym}
            </button>
          ))}
        </div>

        <div className="text-xs text-base-content/60">
          {`Showing ${filteredDecompositions.length} slippage records across candidates`}
        </div>
      </div>

      {/* Section 1: Toxicity & Adverse Selection Matrix */}
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-base-content">
              Top-of-Book Toxicity &amp; Adverse Selection Guard
            </h2>
          </div>
          <span className="badge badge-outline text-xs">ROLLING VPIN &amp; KYLE LAMBDA</span>
        </div>
        <p className="mt-1 text-xs text-base-content/60">
          Ingesting aggregate trades into volume buckets to detect predatory front-running and toxic
          imbalance. Automated fail-closed quote cancellation triggers when VPIN ≥ 0.700 or Hawkes ρ
          ≥ 0.850.
        </p>

        <div className="mt-4 overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr className="border-base-300 text-xs text-base-content/70">
                <th>Symbol</th>
                <th>VPIN</th>
                <th>Kyle&apos;s Lambda (λ)</th>
                <th>Hawkes Spectral Radius (ρ)</th>
                <th>Risk State</th>
                <th>Reservation Shading</th>
                <th>Quote Action</th>
              </tr>
            </thead>
            <tbody>
              {toxicityMetrics.map((m) => (
                <tr key={m.symbol} className="border-base-300/40 hover:bg-base-200/40">
                  <td className="font-bold text-base-content">{m.symbol}</td>
                  <td>
                    <span
                      className={`font-mono font-semibold ${
                        m.vpin >= 0.7 ? 'text-error' : m.vpin >= 0.45 ? 'text-warning' : 'text-success'
                      }`}
                    >
                      {m.vpin.toFixed(4)}
                    </span>
                  </td>
                  <td className="font-mono text-base-content/80">
                    {m.kyles_lambda.toFixed(6)}
                  </td>
                  <td>
                    <span
                      className={`font-mono ${
                        m.hawkes_spectral_radius >= 0.85
                          ? 'text-error font-bold'
                          : m.hawkes_spectral_radius >= 0.65
                          ? 'text-warning'
                          : 'text-success'
                      }`}
                    >
                      {m.hawkes_spectral_radius.toFixed(3)}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`badge badge-sm font-semibold text-[10px] ${
                        m.risk_state === 'TOXIC_RUNAWAY'
                          ? 'badge-error'
                          : m.risk_state === 'ELEVATED'
                          ? 'badge-warning'
                          : 'badge-success'
                      }`}
                    >
                      {m.risk_state}
                    </span>
                  </td>
                  <td className="font-mono text-xs">
                    {`+${m.shading_offset_bps.toFixed(1)} bps`}
                  </td>
                  <td>
                    {m.quotes_pulled ? (
                      <span className="badge badge-error badge-sm gap-1 text-[10px] font-bold">
                        <AlertTriangle className="h-3 w-3" />
                        PULLED_DEFENSE
                      </span>
                    ) : (
                      <span className="badge badge-success badge-sm text-[10px]">
                        POSTED_MAKER
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Section 2: Causal Slippage Attribution Waterfall */}
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-secondary" />
            <h2 className="text-lg font-bold text-base-content">
              Causal Slippage Attribution Engine (4 Orthogonal Components)
            </h2>
          </div>
          <span className="badge badge-outline text-xs">ALMGREN-CHRISS LAW</span>
        </div>
        <p className="mt-1 text-xs text-base-content/60">
          Decomposition of realized slippage into Latency/Delay Slippage, Temporary Market Impact
          (Square-Root Law), Permanent Information Leakage, and Passive Queue Degradation.
        </p>

        <div className="mt-4 overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr className="border-base-300 text-xs text-base-content/70">
                <th>Order ID</th>
                <th>Asset</th>
                <th>Side</th>
                <th>Intended Price</th>
                <th>Fill Price</th>
                <th>Total Slippage</th>
                <th>Delay Slippage</th>
                <th>Temp Impact</th>
                <th>Perm Impact</th>
                <th>Queue Degradation</th>
                <th>Execution Mode</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredDecompositions.map((d) => (
                <tr key={d.order_id} className="border-base-300/40 hover:bg-base-200/40">
                  <td className="font-mono text-xs font-semibold">{d.order_id}</td>
                  <td className="font-bold text-base-content">{d.symbol}</td>
                  <td>
                    <span
                      className={`badge badge-xs font-semibold ${
                        d.side === 'BUY' ? 'badge-success' : 'badge-error'
                      }`}
                    >
                      {d.side}
                    </span>
                  </td>
                  <td className="font-mono text-xs">{`$${d.intended_price.toFixed(2)}`}</td>
                  <td className="font-mono text-xs font-bold">{`$${d.fill_price.toFixed(2)}`}</td>
                  <td>
                    <span className="font-mono font-bold text-base-content">
                      {`${d.total_slippage_bps.toFixed(2)} bps`}
                    </span>
                  </td>
                  <td className="font-mono text-xs text-base-content/70">
                    {`${d.delay_slippage_bps.toFixed(2)} bps`}
                  </td>
                  <td className="font-mono text-xs text-base-content/70">
                    {`${d.temporary_impact_bps.toFixed(2)} bps`}
                  </td>
                  <td className="font-mono text-xs text-base-content/70">
                    {`${d.permanent_impact_bps.toFixed(2)} bps`}
                  </td>
                  <td className="font-mono text-xs text-base-content/70">
                    {`${d.queue_degradation_bps.toFixed(2)} bps`}
                  </td>
                  <td>
                    <span className="badge badge-ghost badge-sm text-[10px]">
                      {d.is_maker ? 'PASSIVE_MAKER' : 'TAKER_BRACKET'}
                    </span>
                  </td>
                  <td>
                    {d.within_tolerance ? (
                      <span className="badge badge-success badge-sm text-[10px]">PASS</span>
                    ) : (
                      <span className="badge badge-error badge-sm text-[10px]">REJECTED</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Section 3: Shaded Quotes & Micro Child Orders */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Shaded Quotes Log */}
        <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-base-content">
              Avellaneda-Stoikov Shaded Quotes
            </h3>
            <span className="badge badge-outline text-xs">HAWKES EXPANSION</span>
          </div>
          <div className="mt-4 space-y-3">
            {filteredQuotes.map((q) => (
              <div
                key={q.quote_id}
                className="rounded-xl border border-base-300/60 bg-base-200/30 p-4 transition-all hover:border-primary/40"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-base-content">{q.symbol}</span>
                    <span
                      className={`badge badge-xs font-semibold ${
                        q.side === 'BUY' ? 'badge-success' : 'badge-error'
                      }`}
                    >
                      {q.side}
                    </span>
                  </div>
                  <span
                    className={`badge badge-sm font-semibold text-[10px] ${
                      q.action === 'PULLED_DEFENSE' ? 'badge-error' : 'badge-success'
                    }`}
                  >
                    {q.action}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <span className="text-base-content/60">Unshaded: </span>
                    <span className="font-mono">{`$${q.unshaded_price.toFixed(2)}`}</span>
                  </div>
                  <div>
                    <span className="text-base-content/60">Shaded: </span>
                    <span className="font-mono font-bold">{`$${q.shaded_price.toFixed(2)}`}</span>
                  </div>
                  <div>
                    <span className="text-base-content/60">Offset: </span>
                    <span className="font-mono text-warning">
                      {`+${q.shading_bps.toFixed(1)} bps`}
                    </span>
                  </div>
                </div>
                <p className="mt-2 text-[11px] italic text-base-content/60">{q.reason}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Micro Child Orders Log */}
        <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-base-content">
              Micro Child Orders Slicing (≤ 5.00 USDT)
            </h3>
            <span className="badge badge-outline text-xs">ROUND_DOWN PRECISION</span>
          </div>
          <div className="mt-4 space-y-3">
            {childOrders.map((c) => (
              <div
                key={c.order_id}
                className="rounded-xl border border-base-300/60 bg-base-200/30 p-4 transition-all hover:border-secondary/40"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold">{c.order_id}</span>
                    <span className="text-xs text-base-content/70">({c.symbol})</span>
                  </div>
                  <span className="badge badge-sm badge-success text-[10px]">{c.status}</span>
                </div>
                <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <span className="text-base-content/60">Qty: </span>
                    <span className="font-mono">{c.quantity}</span>
                  </div>
                  <div>
                    <span className="text-base-content/60">Notional: </span>
                    <span className="font-mono font-bold">{`$${c.notional_usdt.toFixed(2)}`}</span>
                  </div>
                  <div>
                    <span className="text-base-content/60">Fee: </span>
                    <span className="font-mono">{`$${c.fee_usdt.toFixed(5)}`}</span>
                  </div>
                  <div>
                    <span className="text-base-content/60">Slippage: </span>
                    <span className="font-mono">{`$${c.slippage_usdt.toFixed(5)}`}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Section 4: Double-Entry Solvency Meter & Merkle DAG Linkage */}
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-bold text-base-content">
              Double-Entry Mathematical Balance Governance &amp; Merkle Linkage
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <span className="badge badge-accent text-xs">
              {`DRIFT: ${drift.toFixed(2)} USDT`}
            </span>
            <span className="badge badge-success text-xs">
              {isZeroDrift ? 'ZERO DRIFT VERIFIED' : 'DRIFT BREACH'}
            </span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 rounded-xl bg-base-200/40 p-4 sm:grid-cols-4">
          <div>
            <span className="text-xs text-base-content/60">Starting Equity</span>
            <div className="mt-1 font-mono text-base font-bold">
              {`$${startingEquity.toFixed(2)} USDT`}
            </div>
          </div>
          <div>
            <span className="text-xs text-base-content/60">Available Cash</span>
            <div className="mt-1 font-mono text-base font-bold">{`$${cash.toFixed(2)} USDT`}</div>
          </div>
          <div>
            <span className="text-xs text-base-content/60">Allocated Margin</span>
            <div className="mt-1 font-mono text-base font-bold">
              {`$${allocatedMargin.toFixed(2)} USDT`}
            </div>
          </div>
          <div>
            <span className="text-xs text-base-content/60">Realized PnL</span>
            <div
              className={`mt-1 font-mono text-base font-bold ${
                realizedPnl >= 0 ? 'text-success' : 'text-error'
              }`}
            >
              {realizedPnl >= 0 ? `+$${realizedPnl.toFixed(2)}` : `-$${Math.abs(realizedPnl).toFixed(2)}`}
            </div>
          </div>
        </div>

        {/* Cryptographic Linkage */}
        <div className="mt-4 space-y-2 rounded-xl border border-base-300/40 bg-base-200/20 p-4 text-xs font-mono">
          <div className="flex flex-col justify-between gap-1 sm:flex-row">
            <span className="text-base-content/60">Upstream Root (Phase 301):</span>
            <span className="select-all text-base-content">{model.upstreamHash}</span>
          </div>
          {model.phaseHash && (
            <div className="flex flex-col justify-between gap-1 sm:flex-row">
              <span className="text-base-content/60">Phase 302 Hash:</span>
              <span className="select-all text-base-content">{model.phaseHash}</span>
            </div>
          )}
          {model.merkleRoot && (
            <div className="flex flex-col justify-between gap-1 sm:flex-row">
              <span className="text-base-content/60">Phase 302 Merkle Root:</span>
              <span className="select-all font-bold text-primary">{model.merkleRoot}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
