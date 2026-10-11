import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  Crosshair,
  Gauge,
  Radio,
  Shield,
  Target,
} from 'lucide-react'
import { useState } from 'react'
import { PairCandlestickChart } from './pair-candlestick-chart'
import type { OhlcSummary } from '../../lib/chart-indicators'
import type { PositionTelemetry } from './types'
import { ProvenanceBadge } from './provenance-badge'

export interface MarketPositionsCardProps {
  positions: PositionTelemetry[]
  initialExpanded?: boolean | Record<string, boolean>
  defaultInterval?: '15m' | '1h'
}

function formatPrice(val?: number): string {
  if (val === undefined || Number.isNaN(val)) return '0.00'
  if (val < 10) return val.toFixed(4)
  if (val < 1000) return val.toFixed(2)
  return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function MarketPositionsCard({
  positions,
  initialExpanded = false,
  defaultInterval = '15m',
}: MarketPositionsCardProps) {
  const [expandedCharts, setExpandedCharts] = useState<Record<string, boolean>>(() => {
    if (typeof initialExpanded === 'boolean') {
      const init: Record<string, boolean> = {}
      positions.forEach((p) => {
        init[p.symbol] = initialExpanded
      })
      return init
    }
    if (initialExpanded && typeof initialExpanded === 'object') {
      return { ...initialExpanded }
    }
    return {}
  })

  const [intervals, setIntervals] = useState<Record<string, '15m' | '1h'>>({})

  const [indicators, setIndicators] = useState<
    Record<string, { ema50: boolean; ema200: boolean; volume: boolean }>
  >({})

  const [ohlcSummaries, setOhlcSummaries] = useState<Record<string, OhlcSummary | null>>({})

  const toggleChartExpanded = (symbol: string) => {
    setExpandedCharts((prev) => ({
      ...prev,
      [symbol]: !prev[symbol],
    }))
  }

  const handleIntervalChange = (symbol: string, interval: '15m' | '1h') => {
    setIntervals((prev) => ({
      ...prev,
      [symbol]: interval,
    }))
  }

  const handleIndicatorToggle = (
    symbol: string,
    indicator: 'ema50' | 'ema200' | 'volume',
  ) => {
    setIndicators((prev) => {
      const current = prev[symbol] ?? { ema50: true, ema200: true, volume: true }
      return {
        ...prev,
        [symbol]: {
          ...current,
          [indicator]: !current[indicator],
        },
      }
    })
  }

  const handleOhlcUpdate = (symbol: string, summary: OhlcSummary | null) => {
    setOhlcSummaries((prev) => ({
      ...prev,
      [symbol]: summary,
    }))
  }

  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')
  const symbolPills = ['ALL', 'SOL', 'ETH', 'BTC', 'DOGE', 'BNB', 'XRP', 'SUI', 'AVAX']

  const filteredPositions = positions.filter((p) => {
    if (selectedSymbol === 'ALL') return true
    return p.symbol.startsWith(selectedSymbol) || p.symbol === `${selectedSymbol}USDT`
  })

  const allExpanded =
    filteredPositions.length > 0 &&
    filteredPositions.every((p) => Boolean(expandedCharts[p.symbol]))

  const toggleAllCharts = () => {
    const next = !allExpanded
    const updated: Record<string, boolean> = {}
    positions.forEach((p) => {
      updated[p.symbol] = next
    })
    setExpandedCharts(updated)
  }

  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent" />

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.15)]">
            <Radio className="w-5 h-5 text-cyan-400 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Live Positions &amp; Markets
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-400">
                {positions.length > 0 ? `${positions.length} Perpetual Pairs` : '8 Perpetual Pairs'}
              </span>
              <ProvenanceBadge source="LIVE EXCHANGE" />
            </div>
            <p className="text-xs text-zinc-400">
              Real-time mark prices, open positions, and ATR bracket TP/SL target telemetry
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={toggleAllCharts}
            className="inline-flex items-center gap-1.5 text-xs font-mono py-1 px-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/25 text-cyan-400 hover:bg-cyan-500/20 transition-colors"
            data-testid="toggle-all-charts-button"
            title="Expand or collapse all interactive charts simultaneously"
          >
            <span>📈</span>
            <span>{allExpanded ? 'Collapse All Charts' : 'Interactive Chart (All)'}</span>
          </button>
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-semibold py-1 px-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.1)]">
            1.66 : 1 R:R Ratio
          </span>
          <span className="inline-flex items-center gap-1 text-xs font-mono py-1 px-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-zinc-300">
            Maker 0.02% Fee Drag
          </span>
        </div>
      </div>

      {/* Responsive Symbol Selector Pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto py-1 mb-5 no-scrollbar">
        {symbolPills.map((sym) => {
          const isActive = selectedSymbol === sym
          return (
            <button
              key={sym}
              type="button"
              onClick={() => setSelectedSymbol(sym)}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-semibold transition-all shrink-0 ${
                isActive
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                  : 'text-zinc-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
              }`}
              data-testid={`symbol-pill-${sym.toLowerCase()}`}
            >
              {sym === 'ALL' ? 'ALL' : sym}
            </button>
          )
        })}
      </div>

      {/* Grid of Staged Pairs */}
      <div
        className={`grid grid-cols-1 ${
          selectedSymbol === 'ALL'
            ? 'md:grid-cols-2 xl:grid-cols-4'
            : 'max-w-2xl'
        } gap-4 items-start`}
      >
        {filteredPositions.map((pos) => {
          const isScanning = pos.state === 'SCANNING / STANDBY'
          const isLong = pos.state === 'LONG'
          const isShort = pos.state === 'SHORT'
          const pnlPositive = pos.unrealizedPnlUsdt >= 0

          const isExpanded = Boolean(expandedCharts[pos.symbol])
          const activeInterval = intervals[pos.symbol] ?? defaultInterval
          const defaultIndicators = { ema50: true, ema200: true, volume: true }
          const indicatorsForSym = indicators[pos.symbol] ?? defaultIndicators
          const ohlc = ohlcSummaries[pos.symbol] ?? null

          // Calculate TP and SL distances
          const tpDiff = pos.takeProfitPrice && pos.currentPrice
            ? ((pos.takeProfitPrice - pos.currentPrice) / pos.currentPrice) * 100
            : 0
          const slDiff = pos.stopLossPrice && pos.currentPrice
            ? ((pos.currentPrice - pos.stopLossPrice) / pos.currentPrice) * 100
            : 0

          return (
            <div
              key={pos.symbol}
              className="glass-card-subtle rounded-xl p-4 hover:border-cyan-500/30 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden"
              data-testid={`market-pair-card-${pos.symbol.toLowerCase()}`}
            >
              {/* Subtle top indicator bar */}
              <div
                className={`absolute top-0 left-0 right-0 h-[2px] ${
                  isLong
                    ? 'bg-emerald-500 shadow-[0_0_8px_#10b981]'
                    : isShort
                      ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
                      : 'bg-cyan-500/40'
                }`}
              />

              {/* Pair Header & Status Badge */}
              <div>
                <div className="flex items-center justify-between mb-3 pt-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-base text-white group-hover:text-cyan-400 transition-colors">
                      {pos.symbol}
                    </span>
                    <span className="text-[10px] font-mono text-zinc-500 uppercase px-1.5 py-0.5 rounded bg-white/[0.04]">
                      Perp
                    </span>
                  </div>

                  {/* State badge */}
                  <span
                    className={`inline-flex items-center gap-1.5 text-xs font-mono font-semibold py-1 px-2.5 rounded-lg border ${
                      isLong
                        ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.15)]'
                        : isShort
                          ? 'bg-rose-500/15 border-rose-500/30 text-rose-400 shadow-[0_0_10px_rgba(244,63,94,0.15)]'
                          : 'bg-cyan-500/10 border-cyan-500/25 text-cyan-400'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        isLong
                          ? 'bg-emerald-400 animate-ping'
                          : isShort
                            ? 'bg-rose-400 animate-ping'
                            : 'bg-cyan-400 animate-pulse'
                      }`}
                    />
                    {pos.state}
                  </span>
                </div>

                {/* Mark Price & Active Details */}
                <div className="mb-4">
                  <div className="flex items-baseline justify-between mb-1.5">
                    <span className="text-xs text-zinc-400 font-mono">
                      Mark Price:
                    </span>
                    <span className="text-xl font-mono font-bold text-white tracking-tight tabular-nums">
                      ${pos.currentPrice.toLocaleString('en-US', {
                        minimumFractionDigits: pos.currentPrice < 10 ? 4 : 2,
                        maximumFractionDigits: pos.currentPrice < 10 ? 4 : 2,
                      })}
                    </span>
                  </div>

                  {isScanning ? (
                    <div className="p-3 rounded-lg bg-black/20 border border-white/[0.05] text-xs text-zinc-400 mt-2 font-mono flex items-center gap-2.5">
                      <Crosshair className="w-4 h-4 text-cyan-400 shrink-0 animate-spin-slow" />
                      <span className="leading-snug">Scanning 15m liquidity (Capitulation Sweep)...</span>
                    </div>
                  ) : (
                    <div className="p-3 rounded-lg bg-black/25 border border-white/[0.06] mt-2 flex flex-col gap-1.5 text-xs font-mono">
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Entry Price:</span>
                        <span className="font-semibold text-white tabular-nums">
                          ${pos.entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Size / Notional:</span>
                        <span className="font-semibold text-white tabular-nums">
                          {pos.size} (${pos.notionalUsdt.toFixed(2)} USDT)
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Allocated Margin:</span>
                        <span className="font-semibold text-cyan-400 tabular-nums">
                          ${pos.marginUsdt.toFixed(2)} USDT (1x)
                        </span>
                      </div>
                      <div className="flex items-center justify-between pt-1.5 border-t border-white/[0.06]">
                        <span className="text-zinc-400">Unrealized PnL:</span>
                        <span
                          className={`font-bold flex items-center gap-1 tabular-nums ${
                            pnlPositive ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {pnlPositive ? (
                            <ArrowUpRight className="w-3.5 h-3.5 text-emerald-400" />
                          ) : (
                            <ArrowDownRight className="w-3.5 h-3.5 text-rose-400" />
                          )}
                          {pnlPositive ? '+' : ''}${pos.unrealizedPnlUsdt.toFixed(3)} ({pnlPositive ? '+' : ''}{pos.unrealizedPnlPct.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Take-Profit & Stop-Loss Targets (ATR Brackets) */}
              <div className="pt-3 border-t border-white/[0.06] text-xs font-mono flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-emerald-400">
                    <Target className="w-3.5 h-3.5 shrink-0" />
                    <span>Take Profit (TP 2.0x ATR):</span>
                  </div>
                  <div className="flex items-center gap-1.5 font-semibold text-emerald-400 tabular-nums">
                    <span>
                      ${pos.takeProfitPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                    {tpDiff !== 0 && (
                      <span className="text-[10px] text-emerald-400/80">
                        ({tpDiff > 0 ? '+' : ''}{tpDiff.toFixed(1)}%)
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-rose-400">
                    <Shield className="w-3.5 h-3.5 shrink-0" />
                    <span>Stop Loss (SL 1.2x ATR):</span>
                  </div>
                  <div className="flex items-center gap-1.5 font-semibold text-rose-400 tabular-nums">
                    <span>
                      ${pos.stopLossPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                    {slDiff !== 0 && (
                      <span className="text-[10px] text-rose-400/80">
                        (-{slDiff.toFixed(1)}%)
                      </span>
                    )}
                  </div>
                </div>

                {/* Visual ATR Bracket Range Bar */}
                <div className="space-y-1 my-1.5">
                  <div className="w-full bg-black/40 rounded-full h-2 relative overflow-hidden border border-white/[0.06] p-[1px]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-rose-500/70 via-cyan-400 to-emerald-500/70"
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400">
                    <span className="text-rose-400/90 font-medium">SL -1.2x ATR</span>
                    <span className="text-cyan-400 font-semibold">Current Price</span>
                    <span className="text-emerald-400/90 font-medium">TP +2.0x ATR</span>
                  </div>
                </div>

                {/* Distance Meter Gauge */}
                <div className="flex items-center justify-between text-[11px] text-zinc-500 pt-0.5">
                  <span className="flex items-center gap-1 text-zinc-400">
                    <Gauge className="w-3 h-3 text-cyan-400" />
                    Risk/Reward Ratio:
                  </span>
                  <span className="font-mono font-bold text-zinc-300 py-0.5 px-1.5 rounded bg-white/[0.05] border border-white/[0.08]">
                    {pos.riskRewardRatio}
                  </span>
                </div>
              </div>

              {/* Interactive Chart Drawer Toggle Button */}
              <div className="pt-3 border-t border-white/[0.06] mt-3">
                <button
                  type="button"
                  onClick={() => toggleChartExpanded(pos.symbol)}
                  className={`w-full py-2 px-3 rounded-lg text-xs font-mono font-medium flex items-center justify-between transition-all duration-200 border ${
                    isExpanded
                      ? 'bg-cyan-500/15 border-cyan-500/35 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.15)]'
                      : 'bg-white/[0.03] border-white/[0.08] text-zinc-300 hover:bg-white/[0.06] hover:text-white hover:border-cyan-500/30'
                  }`}
                  data-testid={`toggle-chart-${pos.symbol.toLowerCase()}`}
                  aria-expanded={isExpanded}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm">📈</span>
                    <span className="font-semibold tracking-wide">Interactive Chart</span>
                    <span
                      className={`text-[10px] font-mono py-0.5 px-2 rounded-full border ${
                        isExpanded
                          ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
                          : 'bg-white/[0.05] border-white/[0.1] text-zinc-400'
                      }`}
                    >
                      {isExpanded ? 'Expanded' : 'Collapsed'}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-zinc-400">
                    <span className="text-[10px] hidden sm:inline">
                      {isExpanded ? 'Hide' : activeInterval}
                    </span>
                    <ChevronDown
                      className={`w-4 h-4 transition-transform duration-200 ${
                        isExpanded ? 'rotate-180 text-cyan-400' : 'text-zinc-400'
                      }`}
                    />
                  </div>
                </button>
              </div>

              {/* Collapsible Chart Drawer */}
              {isExpanded && (
                <div
                  className="mt-3 pt-3 border-t border-white/[0.08] flex flex-col gap-2.5"
                  data-testid={`chart-drawer-${pos.symbol.toLowerCase()}`}
                >
                  {/* Drawer Header Controls */}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    {/* Timeframe Pills */}
                    <div className="flex items-center gap-1 bg-black/40 p-1 rounded-lg border border-white/[0.06]">
                      <button
                        type="button"
                        onClick={() => handleIntervalChange(pos.symbol, '15m')}
                        className={`px-2.5 py-1 rounded text-xs font-mono font-medium transition-colors ${
                          activeInterval === '15m'
                            ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 shadow-[0_0_8px_rgba(6,182,212,0.2)]'
                            : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
                        }`}
                        data-testid={`timeframe-15m-${pos.symbol.toLowerCase()}`}
                        title="15-minute Scalper"
                      >
                        15m
                      </button>
                      <button
                        type="button"
                        onClick={() => handleIntervalChange(pos.symbol, '1h')}
                        className={`px-2.5 py-1 rounded text-xs font-mono font-medium transition-colors ${
                          activeInterval === '1h'
                            ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 shadow-[0_0_8px_rgba(6,182,212,0.2)]'
                            : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
                        }`}
                        data-testid={`timeframe-1h-${pos.symbol.toLowerCase()}`}
                        title="1-hour Macro Trend"
                      >
                        1h
                      </button>
                    </div>

                    {/* Indicator Toggle Pills */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <button
                        type="button"
                        onClick={() => handleIndicatorToggle(pos.symbol, 'ema50')}
                        className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors border ${
                          indicatorsForSym.ema50
                            ? 'bg-cyan-500/15 border-cyan-500/35 text-cyan-300 font-semibold'
                            : 'bg-white/[0.02] border-white/[0.06] text-zinc-500 line-through'
                        }`}
                        data-testid={`indicator-ema50-${pos.symbol.toLowerCase()}`}
                        title="Toggle 50 EMA (Cyan Line)"
                      >
                        EMA 50
                      </button>
                      <button
                        type="button"
                        onClick={() => handleIndicatorToggle(pos.symbol, 'ema200')}
                        className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors border ${
                          indicatorsForSym.ema200
                            ? 'bg-amber-500/15 border-amber-500/35 text-amber-300 font-semibold'
                            : 'bg-white/[0.02] border-white/[0.06] text-zinc-500 line-through'
                        }`}
                        data-testid={`indicator-ema200-${pos.symbol.toLowerCase()}`}
                        title="Toggle 200 EMA (Amber Line)"
                      >
                        EMA 200
                      </button>
                      <button
                        type="button"
                        onClick={() => handleIndicatorToggle(pos.symbol, 'volume')}
                        className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors border ${
                          indicatorsForSym.volume
                            ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300 font-semibold'
                            : 'bg-white/[0.02] border-white/[0.06] text-zinc-500 line-through'
                        }`}
                        data-testid={`indicator-volume-${pos.symbol.toLowerCase()}`}
                        title="Toggle Volume Histogram"
                      >
                        Volume
                      </button>
                    </div>
                  </div>

                  {/* Current OHLC Badge and 24h High/Low Markers */}
                  <div
                    className="flex flex-wrap items-center justify-between gap-2 p-2 rounded-lg bg-black/30 border border-white/[0.05] text-[11px] font-mono"
                    data-testid={`ohlc-badge-${pos.symbol.toLowerCase()}`}
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-zinc-500 font-bold uppercase">OHLC:</span>
                      <span className="text-zinc-400">
                        O: <span className="text-zinc-200 font-semibold">${ohlc ? formatPrice(ohlc.open) : formatPrice(pos.currentPrice)}</span>
                      </span>
                      <span className="text-zinc-400">
                        H: <span className="text-emerald-400 font-semibold">${ohlc ? formatPrice(ohlc.high) : formatPrice(pos.takeProfitPrice || pos.currentPrice * 1.015)}</span>
                      </span>
                      <span className="text-zinc-400">
                        L: <span className="text-rose-400 font-semibold">${ohlc ? formatPrice(ohlc.low) : formatPrice(pos.stopLossPrice || pos.currentPrice * 0.985)}</span>
                      </span>
                      <span className="text-zinc-400">
                        C: <span className="text-cyan-400 font-semibold">${ohlc ? formatPrice(ohlc.close) : formatPrice(pos.currentPrice)}</span>
                      </span>
                      {ohlc && (
                        <span className="text-zinc-400">
                          Vol: <span className="text-zinc-300 font-semibold">{ohlc.volume.toLocaleString('en-US', { maximumFractionDigits: 1 })}</span>
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2.5 text-zinc-500 ml-auto">
                      <span className="inline-flex items-center gap-1 text-emerald-400/90">
                        <span className="text-zinc-500">24h High:</span>
                        <span className="font-semibold">${ohlc ? formatPrice(ohlc.high24h) : formatPrice(pos.takeProfitPrice || pos.currentPrice * 1.03)}</span>
                      </span>
                      <span className="inline-flex items-center gap-1 text-rose-400/90">
                        <span className="text-zinc-500">24h Low:</span>
                        <span className="font-semibold">${ohlc ? formatPrice(ohlc.low24h) : formatPrice(pos.stopLossPrice || pos.currentPrice * 0.97)}</span>
                      </span>
                    </div>
                  </div>

                  {/* Canvas Container Embedding PairCandlestickChart */}
                  <div className="w-full relative mt-0.5">
                    <PairCandlestickChart
                      symbol={pos.symbol}
                      interval={activeInterval}
                      activeIndicators={indicatorsForSym}
                      position={pos}
                      onOhlcUpdate={(summary) => handleOhlcUpdate(pos.symbol, summary)}
                      className="w-full h-[280px]"
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
