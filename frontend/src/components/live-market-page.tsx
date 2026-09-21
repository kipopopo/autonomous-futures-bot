import { Activity, ArrowDownRight, ArrowUpRight, CheckCircle2, Clock, Radio, Shield, Wifi } from 'lucide-react'

import type { LiveMarketModel } from '@/lib/canary'

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

export function LiveMarketPage({ model }: { model: LiveMarketModel }) {
  const isHealthyGateway = model.gatewayHealth?.is_healthy ?? true
  const heartbeatAge = model.gatewayHealth?.heartbeat_age_ms ?? 0
  const latencyMs = model.gatewayHealth?.latency_ms ?? 0
  const clockSkewMs = model.gatewayHealth?.clock_skew_ms ?? 0
  const isFresh = heartbeatAge <= 500.0

  const symbols = model.candidates.length > 0 ? model.candidates : Object.keys(model.orderbooks)

  return (
    <div className="space-y-6" aria-labelledby="market-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Live Ingress / Market Plane
          </p>
          <h2 id="market-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Phase 292: Live Public Market Ingress (Binance USDⓈ-M)
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-success gap-1 py-2 px-2.5 font-mono text-xs font-semibold">
            <CheckCircle2 size={13} /> PAPER-SAFE
          </span>
          <span className="badge badge-info gap-1 py-2 px-2.5 font-mono text-xs font-semibold">
            READ-ONLY
          </span>
          <span className="badge badge-ghost border-base-content/20 gap-1 py-2 px-2.5 font-mono text-xs font-semibold">
            <Shield size={13} /> EXECUTION AUTHORITY: OFF
          </span>
          <span
            className={`badge ${
              isHealthyGateway ? 'badge-success' : 'badge-warning'
            } gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm`}
          >
            <Radio size={14} className="animate-pulse" />
            {model.status || 'STREAMING'}
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        Continuous, resilient, read-only WebSocket streaming of Binance USDⓈ-M perpetual market feeds across
        the staged candidate universe (BTCUSDT, ETHUSDT, SOLUSDT). Ingests top-of-book depth (@depth5@100ms),
        aggregate trades (@aggTrade), mark prices (@markPrice@1s), and funding rates with zero credentials.
      </p>

      {/* Gateway Telemetry Fact Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Heartbeat Freshness</span>
            <span className="text-primary"><Wifi size={20} /></span>
          </div>
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold font-mono">
                {heartbeatAge.toFixed(1)} ms
              </span>
              <span className={`badge ${isFresh ? 'badge-success' : 'badge-error'} badge-xs font-mono py-1 px-2`}>
                {isFresh ? '≤ 500 ms OK' : 'STALE'}
              </span>
            </div>
            <p className="text-xs opacity-60 mt-1">Packet latency: {latencyMs.toFixed(2)} ms</p>
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Server Clock Skew</span>
            <span className="text-primary"><Clock size={20} /></span>
          </div>
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold font-mono">
                {clockSkewMs >= 0 ? `+${clockSkewMs.toFixed(2)}` : clockSkewMs.toFixed(2)} ms
              </span>
              <span className="badge badge-success badge-xs font-mono py-1 px-2">
                NTP SYNC
              </span>
            </div>
            <p className="text-xs opacity-60 mt-1">Binance /fapi/v1/time sync</p>
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Ingress Packets</span>
            <span className="text-primary"><Activity size={20} /></span>
          </div>
          <div className="mt-2">
            <div className="text-2xl font-bold font-mono">
              {model.gatewayHealth?.total_messages_received ?? 0}
            </div>
            <div className="flex items-center gap-2 text-xs opacity-60 mt-1">
              <span>Gaps: {model.gatewayHealth?.packet_gap_count ?? 0}</span>
              <span>•</span>
              <span>Reconnects: {model.gatewayHealth?.reconnect_count ?? 0}</span>
            </div>
          </div>
        </div>

        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Candidate Universe</span>
            <span className="text-primary"><Shield size={20} /></span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {symbols.length > 0 ? (
              symbols.map((sym) => (
                <span key={sym} className="badge badge-primary badge-outline font-mono text-xs font-semibold py-2 px-2.5">
                  {sym}
                </span>
              ))
            ) : (
              <span className="font-mono text-base opacity-70">—</span>
            )}
          </div>
          <p className="text-xs opacity-60 mt-2">Candidate Registry Manifest v2</p>
        </div>
      </div>

      {/* Mark Price & Funding Rate Indicators */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-6">
          <h3 className="text-lg font-bold tracking-tight mb-4 flex items-center gap-2">
            <Radio size={18} className="text-primary" />
            Mark Prices &amp; Settlement Funding Rates
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {symbols.map((sym) => {
              const mark = model.markPrices[sym]
              return (
                <div key={sym} className="bg-base-300/60 p-4 rounded-xl border border-base-300 flex flex-col justify-between">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-base text-primary">{sym}</span>
                    <span className="badge badge-sm badge-ghost font-mono">1s</span>
                  </div>
                  <div className="my-3">
                    <div className="text-2xl font-mono font-bold text-base-content">
                      {mark ? `${mark.mark_price} USDT` : '—'}
                    </div>
                    <div className="text-xs opacity-60 mt-1 flex justify-between">
                      <span>Index: {mark?.index_price || '—'}</span>
                      {mark?.estimated_settle_price && <span>Settle: {mark.estimated_settle_price}</span>}
                    </div>
                  </div>
                  <div className="border-t border-base-content/10 pt-2 flex items-center justify-between text-xs font-mono">
                    <span className="opacity-70">Funding:</span>
                    <span className="text-info font-semibold">
                      {mark?.funding_rate ? `${(Number.parseFloat(mark.funding_rate) * 100).toFixed(4)}%` : '—'}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Orderbook Depth Ladders */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-6">
          <h3 className="text-lg font-bold tracking-tight mb-4 flex items-center gap-2">
            <Activity size={18} className="text-primary" />
            Orderbook Depth Ladders (Top 5 Bids &amp; Asks)
          </h3>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {symbols.map((sym) => {
              const book = model.orderbooks[sym]
              const bids = book?.bids || []
              const asks = book?.asks || []

              return (
                <div key={sym} className="bg-base-300/40 p-4 rounded-xl border border-base-300 flex flex-col justify-between">
                  <div className="flex items-center justify-between pb-3 border-b border-base-300 mb-3">
                    <span className="font-mono font-bold text-base text-base-content">{sym}</span>
                    <div className="flex items-center gap-2">
                      <span className="badge badge-xs font-mono badge-outline">depth5@100ms</span>
                      <span className="text-xs font-mono opacity-60">u:{book?.last_update_id || '—'}</span>
                    </div>
                  </div>

                  {/* Asks (displayed in reverse order so best ask is near the spread) */}
                  <div className="space-y-1 font-mono text-xs mb-2">
                    <span className="text-[10px] uppercase font-semibold text-error/70 tracking-wider">Asks</span>
                    {[...asks].reverse().map((ask, idx) => (
                      <div key={idx} className="flex justify-between items-center text-error px-1 py-0.5 rounded bg-error/5">
                        <span>{ask.price}</span>
                        <span className="opacity-80">{ask.quantity}</span>
                      </div>
                    ))}
                  </div>

                  {/* Spread Bar */}
                  <div className="py-2 px-3 my-2 rounded-lg bg-base-200 border border-base-300/80 flex items-center justify-between text-xs font-mono">
                    <span className="opacity-70">Spread:</span>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-base-content">
                        {book?.best_bid && book?.best_ask
                          ? (Number.parseFloat(book.best_ask) - Number.parseFloat(book.best_bid)).toFixed(2)
                          : '—'}
                      </span>
                      <span className="badge badge-xs font-mono badge-ghost">
                        {book?.spread_bps ? `${Number.parseFloat(book.spread_bps).toFixed(2)} bps` : '—'}
                      </span>
                    </div>
                  </div>

                  {/* Bids */}
                  <div className="space-y-1 font-mono text-xs mt-2">
                    <span className="text-[10px] uppercase font-semibold text-success/70 tracking-wider">Bids</span>
                    {bids.map((bid, idx) => (
                      <div key={idx} className="flex justify-between items-center text-success px-1 py-0.5 rounded bg-success/5">
                        <span>{bid.price}</span>
                        <span className="opacity-80">{bid.quantity}</span>
                      </div>
                    ))}
                  </div>

                  <div className="mt-3 pt-2 border-t border-base-content/10 text-[11px] font-mono opacity-60 flex justify-between">
                    <span>Best Bid: {book?.best_bid || '—'}</span>
                    <span>Best Ask: {book?.best_ask || '—'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Real-Time Aggregate Trade Stream */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold tracking-tight flex items-center gap-2">
              <Radio size={18} className="text-primary" />
              Live Aggregate Trade Stream (@aggTrade)
            </h3>
            <span className="text-xs font-mono opacity-70">
              Showing {model.recentTrades.length} recent fills
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-sm table-zebra w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-base-300 text-base-content/70">
                  <th>Symbol</th>
                  <th>Trade ID</th>
                  <th>Side</th>
                  <th>Price (USDT)</th>
                  <th>Quantity</th>
                  <th>Notional (USDT)</th>
                  <th>Time (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {model.recentTrades.length > 0 ? (
                  model.recentTrades.map((trade) => {
                    const priceNum = Number.parseFloat(trade.price)
                    const qtyNum = Number.parseFloat(trade.quantity)
                    const notional = (priceNum * qtyNum).toFixed(2)

                    return (
                      <tr key={`${trade.symbol}-${trade.aggregate_trade_id}`}>
                        <td className="font-bold text-primary">{trade.symbol}</td>
                        <td className="opacity-70">{trade.aggregate_trade_id}</td>
                        <td>
                          {trade.is_buyer_maker ? (
                            <span className="badge badge-xs badge-error gap-1">
                              <ArrowDownRight size={10} /> SELL
                            </span>
                          ) : (
                            <span className="badge badge-xs badge-success gap-1">
                              <ArrowUpRight size={10} /> BUY
                            </span>
                          )}
                        </td>
                        <td className={trade.is_buyer_maker ? 'text-error font-semibold' : 'text-success font-semibold'}>
                          {trade.price}
                        </td>
                        <td>{trade.quantity}</td>
                        <td>{notional}</td>
                        <td className="opacity-70">{formatMyt(trade.trade_time_utc)}</td>
                      </tr>
                    )
                  })
                ) : (
                  <tr>
                    <td colSpan={7} className="text-center py-6 opacity-60">
                      No live aggregate trades recorded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
