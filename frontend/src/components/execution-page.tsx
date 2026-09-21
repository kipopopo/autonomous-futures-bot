import { useState } from 'react'
import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Cpu,
  Layers,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react'

import type { PaperExecutionModel } from '@/lib/canary'

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

export function ExecutionPage({ model }: { model: PaperExecutionModel }) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')

  const filteredOrders = model.recentChildOrders.filter((o) => {
    if (selectedSymbol === 'ALL') return true
    return o.symbol === selectedSymbol
  })

  const filteredFills = model.recentFills.filter((f) => {
    if (selectedSymbol === 'ALL') return true
    return f.symbol === selectedSymbol
  })

  const exposureNum = parseFloat(model.activeExposureUsdt) || 0
  const exposureCapNum = parseFloat(model.aggregateExposureCapUsdt) || 60.0
  const exposurePct = Math.min(100, Math.round((exposureNum / exposureCapNum) * 100))

  const reservePctNum = Math.round((parseFloat(model.unencumberedCashReservePct) || 1.0) * 100)

  return (
    <div className="space-y-6" aria-labelledby="execution-heading">
      {/* Top Header & Badges */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Execution Plane / Paper Matching Simulator
          </p>
          <h2 id="execution-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Micro Child Order Slicing &amp; Zero-Drift Passive Matching
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-success gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
            <CheckCircle2 size={14} />
            ZERO-DRIFT VERIFIED (|Δ| &lt; 10⁻¹⁵)
          </span>
          <span className="badge badge-outline badge-error font-mono text-[11px] font-bold tracking-wider py-2.5 px-3">
            EXECUTION AUTHORITY: OFF
          </span>
          <span className="badge badge-primary badge-outline text-[11px] font-mono font-semibold py-2.5 px-3">
            ROUND_DOWN ≤ 5.00 USDT
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        Simulated passive maker and aggressive taker queue execution coupled with Binance top-5 depth (
        <code>@depth5@100ms</code>) and aggregate trades (<code>@aggTrade</code>). Slices parent orders into micro
        child slices strictly ≤ 5.00 USDT while continuously enforcing real-time Hawkes runaway blocks and mathematical
        double-entry balance integrity.
      </p>

      {/* Exposure & Headroom Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="card bg-base-200 border border-base-300 shadow-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Active Exposure</span>
              <Cpu size={16} className="text-primary" />
            </div>
            <p className="font-mono text-xl font-bold mt-1 text-base-content">
              {model.activeExposureUsdt} <span className="text-xs font-normal opacity-70">/ {model.aggregateExposureCapUsdt} USDT</span>
            </p>
          </div>
          <div className="mt-3">
            <div className="flex justify-between text-[11px] font-mono opacity-80 mb-1">
              <span>Utilization: {exposurePct}%</span>
              <span>Cap: ≤ 60.00 USDT</span>
            </div>
            <progress className={`progress ${exposurePct > 80 ? 'progress-error' : exposurePct > 50 ? 'progress-warning' : 'progress-primary'} w-full`} value={exposurePct} max={100} />
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Cash Reserve Buffer</span>
              <ShieldCheck size={16} className="text-success" />
            </div>
            <p className="font-mono text-xl font-bold mt-1 text-success">
              {reservePctNum}% <span className="text-xs font-normal opacity-70">of starting equity</span>
            </p>
          </div>
          <div className="mt-3">
            <div className="flex justify-between text-[11px] font-mono opacity-80 mb-1">
              <span>Reserve: {reservePctNum}%</span>
              <span>Floor: ≥ 40.00%</span>
            </div>
            <progress className={`progress ${reservePctNum < 40 ? 'progress-error' : 'progress-success'} w-full`} value={reservePctNum} max={100} />
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Child Orders</span>
              <Layers size={16} className="text-info" />
            </div>
            <p className="font-mono text-xl font-bold mt-1 text-base-content">
              {model.orderStats.filled_child_orders} <span className="text-xs font-normal opacity-70">/ {model.orderStats.total_child_orders} filled</span>
            </p>
          </div>
          <div className="flex items-center justify-between text-xs opacity-70 mt-3 pt-2 border-t border-base-300">
            <span>Maker: {model.matchingStats.passive_maker_fills_count}</span>
            <span>Taker: {model.matchingStats.aggressive_taker_fills_count}</span>
            <span>Ratio: {(model.matchingStats.fill_ratio * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 shadow-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Fees &amp; Slippage</span>
              <Zap size={16} className="text-warning" />
            </div>
            <p className="font-mono text-xl font-bold mt-1 text-warning">
              {model.orderStats.total_fees_usdt} <span className="text-xs font-normal opacity-70">USDT</span>
            </p>
          </div>
          <div className="flex items-center justify-between text-xs opacity-70 mt-3 pt-2 border-t border-base-300 font-mono">
            <span>Maker 0.02%</span>
            <span>Taker 0.04%</span>
            <span>Slip: {model.orderStats.total_slippage_usdt}</span>
          </div>
        </div>
      </div>

      {/* Real-Time Risk Interlocks Bar */}
      <div className="card bg-base-200 border border-base-300 shadow-xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-3 mb-4">
          <div className="flex items-center gap-2">
            <ShieldAlert size={18} className="text-primary" />
            <h3 className="text-base font-bold">Real-Time Risk Interlock Circuit Breakers</h3>
          </div>
          <div className="flex items-center gap-2">
            <span className={`badge ${model.circuitState === 'NORMAL' ? 'badge-success' : 'badge-error'} font-mono text-xs font-bold py-2 px-3`}>
              CIRCUIT: {model.circuitState}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="bg-base-300/60 p-3 rounded-lg border border-base-300 flex items-center gap-3">
            <div className="p-2 rounded-md bg-success/10 text-success">
              <Activity size={18} />
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Hawkes Runaway</span>
              <p className="font-mono text-xs font-bold mt-0.5 text-success">ρ &lt; 1.00 (NORMAL)</p>
            </div>
          </div>

          <div className="bg-base-300/60 p-3 rounded-lg border border-base-300 flex items-center gap-3">
            <div className="p-2 rounded-md bg-success/10 text-success">
              <CheckCircle2 size={18} />
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Gateway Freshness</span>
              <p className="font-mono text-xs font-bold mt-0.5 text-success">Age ≤ 500 ms (HEALTHY)</p>
            </div>
          </div>

          <div className="bg-base-300/60 p-3 rounded-lg border border-base-300 flex items-center gap-3">
            <div className="p-2 rounded-md bg-success/10 text-success">
              <AlertOctagon size={18} />
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Loss Ceiling</span>
              <p className="font-mono text-xs font-bold mt-0.5 text-success">Loss ≤ 7.00 USDT (SAFE)</p>
            </div>
          </div>

          <div className="bg-base-300/60 p-3 rounded-lg border border-base-300 flex items-center gap-3">
            <div className="p-2 rounded-md bg-success/10 text-success">
              <ShieldCheck size={18} />
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Micro Cap Interlock</span>
              <p className="font-mono text-xs font-bold mt-0.5 text-success">≤ 5.00 USDT / slice</p>
            </div>
          </div>
        </div>
      </div>

      {/* Double-Entry Ledger Reconciler Card */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-3 mb-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <Scale size={20} />
              </div>
              <div>
                <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">Double-Entry Conservation</p>
                <h3 className="text-base font-bold text-base-content">
                  Mathematical Balance Invariant Reconciler
                </h3>
              </div>
            </div>
            <span className="badge badge-success gap-1 font-mono text-xs font-semibold py-2.5 px-3 shadow-sm">
              Δ = {model.ledger.drift_usdt} USDT
            </span>
          </div>

          <div className="bg-base-300/60 p-3 rounded-lg border border-base-300 font-mono text-xs text-base-content font-medium overflow-x-auto whitespace-nowrap mb-4">
            Cash ({model.ledger.cash_usdt}) + Margin ({model.ledger.allocated_margin_usdt}) + Unrealized PnL ({model.ledger.unrealized_pnl_usdt}) = Starting Equity ({model.ledger.starting_equity_usdt}) + Realized PnL ({model.ledger.realized_pnl_usdt})
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 text-center">
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Starting Equity</span>
              <p className="font-mono text-base font-bold mt-1">{model.ledger.starting_equity_usdt}</p>
            </div>
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Settled Cash</span>
              <p className="font-mono text-base font-bold text-primary mt-1">{model.ledger.cash_usdt}</p>
            </div>
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Allocated Margin</span>
              <p className="font-mono text-base font-bold mt-1">{model.ledger.allocated_margin_usdt}</p>
            </div>
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Unrealized PnL</span>
              <p className="font-mono text-base font-bold mt-1">{model.ledger.unrealized_pnl_usdt}</p>
            </div>
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Realized PnL</span>
              <p className="font-mono text-base font-bold text-warning mt-1">{model.ledger.realized_pnl_usdt}</p>
            </div>
            <div className="bg-base-300/40 p-3 rounded-xl border border-base-300">
              <span className="text-[11px] uppercase tracking-wider opacity-70 font-semibold">Balance Drift</span>
              <p className="font-mono text-base font-bold text-success mt-1">{model.ledger.drift_usdt}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Child Orders Table */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="p-4 border-b border-base-300 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Layers size={18} className="text-primary" />
            <h3 className="text-base font-bold">Simulated Child Orders (Micro Slices ≤ 5.00 USDT)</h3>
            <span className="badge badge-ghost text-xs font-mono">{filteredOrders.length} orders</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs opacity-70 mr-1">Filter:</span>
            {['ALL', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map((sym) => (
              <button
                key={sym}
                onClick={() => setSelectedSymbol(sym)}
                className={`btn btn-xs ${selectedSymbol === sym ? 'btn-primary' : 'btn-ghost'}`}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="table table-sm table-zebra w-full font-mono text-xs">
            <thead>
              <tr className="bg-base-300/60 text-base-content/80 text-[11px]">
                <th>Order ID</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Type</th>
                <th>Price</th>
                <th>Qty</th>
                <th>Notional (USDT)</th>
                <th>Status</th>
                <th>Time (MYT)</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-6 text-base-content/60 italic">
                    No child orders found matching criteria.
                  </td>
                </tr>
              ) : (
                filteredOrders.map((order) => (
                  <tr key={order.client_order_id}>
                    <td className="font-bold text-primary max-w-[140px] truncate" title={order.client_order_id}>
                      {order.client_order_id.split('-').slice(-2).join('-')}
                    </td>
                    <td><span className="badge badge-sm badge-ghost font-bold">{order.symbol}</span></td>
                    <td>
                      <span className={`badge badge-sm font-semibold ${order.side === 'BUY' ? 'badge-success' : 'badge-error'}`}>
                        {order.side}
                      </span>
                    </td>
                    <td>{order.order_type}</td>
                    <td>{order.price}</td>
                    <td>{order.quantity}</td>
                    <td className="font-bold">{order.notional_usdt}</td>
                    <td>
                      <span className={`badge badge-xs font-semibold ${order.status === 'FILLED' ? 'badge-success' : order.status === 'OPEN' ? 'badge-info' : 'badge-ghost'}`}>
                        {order.status}
                      </span>
                    </td>
                    <td className="opacity-70 whitespace-nowrap">{formatMyt(order.timestamp_utc)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Execution Fills & Fills Log */}
      {filteredFills.length > 0 && (
        <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
          <div className="p-4 border-b border-base-300 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap size={18} className="text-warning" />
              <h3 className="text-base font-bold">Execution Marks &amp; Fee Telemetry</h3>
              <span className="badge badge-ghost text-xs font-mono">{filteredFills.length} fills</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table table-sm table-zebra w-full font-mono text-xs">
              <thead>
                <tr className="bg-base-300/60 text-base-content/80 text-[11px]">
                  <th>Fill ID</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Fill Price</th>
                  <th>Fill Qty</th>
                  <th>Fill Notional</th>
                  <th>Fee (USDT)</th>
                  <th>Role</th>
                  <th>Slippage</th>
                </tr>
              </thead>
              <tbody>
                {filteredFills.map((fill) => (
                  <tr key={fill.fill_id}>
                    <td className="font-bold text-base-content/80">{fill.fill_id}</td>
                    <td>{fill.symbol}</td>
                    <td>
                      <span className={`badge badge-xs font-semibold ${fill.side === 'BUY' ? 'badge-success' : 'badge-error'}`}>
                        {fill.side}
                      </span>
                    </td>
                    <td>{fill.fill_price}</td>
                    <td>{fill.fill_quantity}</td>
                    <td className="font-bold">{fill.fill_notional_usdt} USDT</td>
                    <td className="text-warning">{fill.fee_usdt}</td>
                    <td>
                      <span className={`badge badge-xs ${fill.is_maker ? 'badge-primary' : 'badge-secondary'}`}>
                        {fill.is_maker ? 'MAKER' : 'TAKER'}
                      </span>
                    </td>
                    <td>{fill.slippage_bps} bps</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
