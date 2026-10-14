import { useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  Crosshair,
  Gauge,
  Radio,
  Shield,
  Target,
  Zap,
} from 'lucide-react'
import type { BracketPositionsModel, LiveMarketModel } from '@/lib/canary'
import type { PositionTelemetry, PairTicker } from './mission-control/types'
import { ProvenanceBadge } from './mission-control/provenance-badge'

export interface ExecutivePositionsPageProps {
  positions: PositionTelemetry[]
  pairTickers?: PairTicker[]
  bracketPositionsModel: BracketPositionsModel
  liveMarketModel: LiveMarketModel
}

function formatPrice(val?: number): string {
  if (val === undefined || Number.isNaN(val)) return '0.00'
  if (val < 10) return val.toFixed(4)
  if (val < 1000) return val.toFixed(2)
  return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function ExecutivePositionsPage({
  positions,
  pairTickers,
  bracketPositionsModel,
  liveMarketModel: _liveMarketModel,
}: ExecutivePositionsPageProps) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')
  const symbolPills = ['ALL', 'SOL', 'ETH', 'BTC', 'DOGE', 'BNB', 'XRP', 'SUI', 'AVAX', 'NEAR', 'LINK', 'APT', 'ADA']

  const filteredPositions = positions.filter((p) => {
    if (selectedSymbol === 'ALL') return true
    return p.symbol.startsWith(selectedSymbol) || p.symbol === `${selectedSymbol}USDT`
  })

  const activeCount = positions.filter((p) => p.state !== 'SCANNING / STANDBY').length
  const liveBrackets =
    bracketPositionsModel.phase === 'phase_301'
      ? []
      : bracketPositionsModel.brackets

  return (
    <div className="w-full space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-5 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
              <Radio className="w-5 h-5 text-cyan-400 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-bold tracking-tight text-white">
                  Detailed Positions &amp; Markets
                </h1>
                <span className="badge badge-sm font-mono font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                  {activeCount} Open / {positions.length} Monitored
                </span>
                <ProvenanceBadge source="LIVE EXCHANGE" />
              </div>
              <p className="text-xs text-white/50">
                Binance Futures perpetual market position telemetry, ATR bracket orders, and mark price depth
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="badge badge-sm font-mono font-semibold py-1 px-3 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              1.66:1 Target R:R
            </span>
            <span className="badge badge-sm badge-outline font-mono border-white/20 text-white/70">
              0.5% Risk / 5% Daily Loss
            </span>
          </div>
        </div>
      </div>

      {/* R-NEW: Real-Time Crypto Pairs Last Price Ticker (At a Glance) */}
      <div className="glass-panel p-5 relative overflow-hidden" data-testid="last-price-ticker-section">
        <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent" />
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.15)]">
              <Zap className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-bold tracking-tight text-white">
                  Real-Time Crypto Pairs Last Price Ticker (At a Glance)
                </h2>
                <span className="badge badge-xs font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                  LIVE STREAM
                </span>
                <span className="text-[10px] font-mono text-zinc-400 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.08]">
                  12 Pairs
                </span>
              </div>
              <p className="text-xs text-zinc-400">
                Live Last Traded Price vs Fair Mark Price and Funding Basis across all 12 perpetual pairs
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400 bg-cyan-500/10 px-2.5 py-1 rounded-lg border border-cyan-500/20 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>Binance Futures Gateway</span>
            </span>
          </div>
        </div>

        {/* Ticker Cards Grid (All 12 Pairs in a Glance) */}
        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-4 gap-3">
          {(pairTickers && pairTickers.length > 0
            ? pairTickers
            : positions.map((p) => ({
                symbol: p.symbol,
                lastPrice: p.lastPrice || p.currentPrice,
                markPrice: p.markPrice || p.currentPrice,
                indexPrice: p.indexPrice || p.markPrice || p.currentPrice,
                fundingRate: p.fundingRate ?? 0.0001,
                basis: p.basis ?? 0,
                basisPct: p.basisPct ?? 0,
              }))
          ).map((ticker) => {
            const isSelected = selectedSymbol !== 'ALL' && (ticker.symbol.startsWith(selectedSymbol) || ticker.symbol === `${selectedSymbol}USDT`)
            const isPremium = (ticker.basis ?? 0) >= 0

            return (
              <div
                key={ticker.symbol}
                onClick={() => setSelectedSymbol(selectedSymbol === ticker.symbol.replace('USDT', '') ? 'ALL' : ticker.symbol.replace('USDT', ''))}
                className={`p-3.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between ${
                  isSelected
                    ? 'bg-cyan-500/15 border-cyan-500/50 shadow-[0_0_15px_rgba(6,182,212,0.15)] ring-1 ring-cyan-500/40'
                    : 'bg-white/[0.02] border-white/[0.07] hover:bg-white/[0.05] hover:border-white/[0.15]'
                }`}
                title={`Click to filter table by ${ticker.symbol}`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-mono font-bold text-xs text-white flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      {ticker.symbol}
                    </span>
                    <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-300">
                      PERP
                    </span>
                  </div>

                  {/* Last Price Highlight */}
                  <div className="mb-2">
                    <div className="text-[10px] text-zinc-400 font-mono flex items-center justify-between">
                      <span>Last Price:</span>
                      <span className="text-[10px] text-cyan-400 font-semibold">LIVE</span>
                    </div>
                    <div className="text-base sm:text-lg font-mono font-bold text-white tracking-tight tabular-nums">
                      ${formatPrice(ticker.lastPrice)}
                    </div>
                  </div>
                </div>

                {/* Mark Price & Spread Basis Footer */}
                <div className="pt-2 border-t border-white/[0.06] space-y-1 text-[11px] font-mono">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">Mark:</span>
                    <span className="text-zinc-200 font-semibold tabular-nums">
                      ${formatPrice(ticker.markPrice)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">Basis:</span>
                    <span className={`font-semibold tabular-nums text-[10px] ${
                      isPremium ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {ticker.basis > 0
                        ? `+$${ticker.basis.toFixed(4)}`
                        : ticker.basis < 0
                          ? `-$${Math.abs(ticker.basis).toFixed(4)}`
                          : '$0.0000'}{' '}
                      ({ticker.basisPct > 0 ? '+' : ''}
                      {ticker.basisPct.toFixed(3)}%)
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400">8h Fund:</span>
                    <span className="text-zinc-300 text-[10px] tabular-nums">
                      {(ticker.fundingRate * 100).toFixed(4)}%
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Main Multi-Asset Positions Table */}
      <div className="glass-panel p-5 relative">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-base font-bold tracking-tight text-white flex items-center gap-2">
            <Crosshair className="w-4 h-4 text-cyan-400" />
            Current Staged Asset Positions &amp; Targets
          </h2>

          {/* Symbol Filter Controls */}
          <div className="flex flex-wrap items-center gap-1 bg-white/[0.03] p-1 rounded-xl border border-white/[0.08]">
            {symbolPills.map((sym) => (
              <button
                key={sym}
                type="button"
                onClick={() => setSelectedSymbol(sym)}
                className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold transition-all ${
                  selectedSymbol === sym
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
                }`}
              >
                {sym === 'ALL' ? 'ALL' : sym}
              </button>
            ))}
          </div>
        </div>

        <div
          className={`grid grid-cols-1 ${
            selectedSymbol === 'ALL'
              ? 'md:grid-cols-2 xl:grid-cols-4'
              : 'max-w-2xl'
          } gap-4 mb-6`}
        >
          {filteredPositions.map((pos) => {
            const isScanning = pos.state === 'SCANNING / STANDBY'
            const pnlPositive = pos.unrealizedPnlUsdt >= 0

            return (
              <div
                key={pos.symbol}
                className="glass-card-subtle p-4 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-base text-base-content">
                        {pos.symbol}
                      </span>
                      <span className="badge badge-xs badge-neutral font-mono">Perp</span>
                    </div>
                    <span
                      className={`badge badge-sm font-mono font-semibold ${
                        isScanning
                          ? 'badge-outline border-cyan-500/40 text-cyan-400'
                          : pos.state === 'LONG'
                            ? 'badge-success text-white'
                            : 'badge-error text-white'
                      }`}
                    >
                      {pos.state}
                    </span>
                  </div>

                  <div className="space-y-2 text-xs font-mono mb-4">
                    <div className="flex justify-between items-baseline">
                      <span className="text-base-content/60 flex items-center gap-1">
                        <span>Mark Price:</span>
                        <span className="text-[10px] text-zinc-400 font-normal">(Fair Val)</span>
                      </span>
                      <span className="font-bold text-base-content font-mono">
                        ${formatPrice(pos.markPrice || pos.currentPrice)}
                      </span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-base-content/60 flex items-center gap-1">
                        <span>Last Price:</span>
                        <span className="text-[10px] text-cyan-400 font-normal">(Ticker)</span>
                      </span>
                      <span className="font-semibold text-cyan-300 font-mono">
                        ${formatPrice(pos.lastPrice || pos.currentPrice)}
                      </span>
                    </div>
                    <div className="flex justify-between items-baseline text-[11px] font-mono">
                      <span className="text-base-content/50">Basis Spread:</span>
                      <span
                        className={`font-semibold tabular-nums ${
                          (pos.basis ?? 0) > 0
                            ? 'text-emerald-400'
                            : (pos.basis ?? 0) < 0
                              ? 'text-rose-400'
                              : 'text-base-content/60'
                        }`}
                      >
                        {(pos.basis ?? 0) > 0
                          ? `+$${(pos.basis ?? 0).toFixed(4)}`
                          : (pos.basis ?? 0) < 0
                            ? `-$${Math.abs(pos.basis ?? 0).toFixed(4)}`
                            : '$0.0000'}{' '}
                        ({(pos.basisPct ?? 0) > 0 ? '+' : ''}
                        {(pos.basisPct ?? 0).toFixed(3)}%)
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-base-content/60">Entry Price:</span>
                      <span className="text-base-content font-semibold">
                        {pos.entryPrice > 0 ? `$${formatPrice(pos.entryPrice)}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-base-content/60">Size / Notional:</span>
                      <span className="text-base-content">
                        {pos.size} (${pos.notionalUsdt.toFixed(2)} USDT)
                      </span>
                    </div>
                    <div className="flex justify-between pt-1 border-t border-base-300/60">
                      <span className="text-base-content/60">Unrealized PnL:</span>
                      <span
                        className={`font-bold flex items-center gap-0.5 ${
                          pnlPositive ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {pnlPositive ? (
                          <ArrowUpRight className="w-3.5 h-3.5" />
                        ) : (
                          <ArrowDownRight className="w-3.5 h-3.5" />
                        )}
                        {pnlPositive ? '+' : ''}${pos.unrealizedPnlUsdt.toFixed(3)} ({pnlPositive ? '+' : ''}{pos.unrealizedPnlPct.toFixed(2)}%)
                      </span>
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-base-300/60 text-xs font-mono space-y-1.5">
                  <div className="flex justify-between text-emerald-400">
                    <span className="flex items-center gap-1">
                      <Target className="w-3.5 h-3.5" /> TP 2.0x ATR:
                    </span>
                    <span className="font-semibold">
                      ${formatPrice(pos.takeProfitPrice)}
                    </span>
                  </div>
                  <div className="flex justify-between text-rose-400">
                    <span className="flex items-center gap-1">
                      <Shield className="w-3.5 h-3.5" /> SL 1.2x ATR:
                    </span>
                    <span className="font-semibold">
                      ${formatPrice(pos.stopLossPrice)}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Dynamic Trailing Stop & Bracket Orders Section */}
        <div className="pt-4 border-t border-white/[0.06]">
          <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
            <Gauge className="w-4 h-4 text-cyan-400" />
            Dynamic Trailing Stop Bracket Orders
          </h3>

          <div className="overflow-x-auto">
            <table className="table table-sm w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-white/[0.08] text-white/50 text-[11px] uppercase">
                  <th>Bracket ID</th>
                  <th>Symbol</th>
                  <th>Bracket Type</th>
                  <th>Entry Price</th>
                  <th>Trigger Price (TP/SL)</th>
                  <th>Ratchet Watermark</th>
                  <th>Callback Rate</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {liveBrackets.length > 0 ? (
                  liveBrackets.map((b) => (
                    <tr key={b.bracket_id} className="hover:bg-white/[0.02] border-b border-white/[0.04]">
                      <td className="font-semibold text-cyan-400">{b.bracket_id}</td>
                      <td>{b.symbol}</td>
                      <td>
                        <span className="badge badge-xs badge-outline border-white/20 text-white/70">{b.bracket_type}</span>
                      </td>
                      <td>{`$${b.entry_price.toFixed(2)}`}</td>
                      <td className="font-bold text-white">
                        {b.trigger_price != null ? `$${b.trigger_price.toFixed(2)}` : '—'}
                      </td>
                      <td>
                        {b.ratchet_watermark != null ? `$${b.ratchet_watermark.toFixed(2)}` : '—'}
                      </td>
                      <td>
                        {b.callback_rate_pct != null ? `${(b.callback_rate_pct * 100).toFixed(2)}%` : '—'}
                      </td>
                      <td>
                        <span className="badge badge-xs badge-success py-1 px-2 font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                          {b.status}
                        </span>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={8} className="text-center py-4 text-white/40">
                      No active brackets currently.
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
