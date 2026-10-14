import { useMemo } from 'react'
import {
  ChevronRight,
  Radio,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import type {
  PairTicker,
  PositionTelemetry,
  IctPairSignal,
  ScalperCriteria,
  BtcMacroTrend,
} from './types'
import { ProvenanceBadge } from './provenance-badge'
import { evaluatePairEntry } from '../../lib/pair-entry-status'

export interface PairPriceTickersCardProps {
  positions: PositionTelemetry[]
  pairTickers?: PairTicker[]
  ictSignals?: Record<string, IctPairSignal> | null
  scalperCriteria?: ScalperCriteria
  btcMacroTrend?: BtcMacroTrend
  onSelectPair?: (symbol: string) => void
}

function formatPrice(val?: number): string {
  if (val === undefined || Number.isNaN(val) || val === null) return '0.00'
  if (val < 0.1) return val.toFixed(6)
  if (val < 10) return val.toFixed(4)
  if (val < 1000) return val.toFixed(2)
  return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function PairPriceTickersCard({
  positions,
  pairTickers,
  ictSignals,
  scalperCriteria,
  btcMacroTrend,
  onSelectPair,
}: PairPriceTickersCardProps) {
  const resolvedTickers: PairTicker[] = useMemo(() => {
    if (pairTickers && pairTickers.length > 0) return pairTickers
    return positions.map((p) => ({
      symbol: p.symbol,
      lastPrice: p.lastPrice || p.currentPrice,
      markPrice: p.markPrice || p.currentPrice,
      indexPrice: p.indexPrice || p.markPrice || p.currentPrice,
      fundingRate: p.fundingRate ?? 0.0001,
      basis: p.basis ?? 0,
      basisPct: p.basisPct ?? 0,
    }))
  }, [positions, pairTickers])

  const positionMap = useMemo(() => {
    const map = new Map<string, PositionTelemetry>()
    positions.forEach((p) => map.set(p.symbol, p))
    return map
  }, [positions])

  const tickerMap = useMemo(() => {
    const map = new Map<string, PairTicker>()
    resolvedTickers.forEach((t) => map.set(t.symbol, t))
    return map
  }, [resolvedTickers])

  // All 12 canonical symbols ordered logically
  const allSymbols = useMemo(() => {
    const canonicalOrder = [
      'BTCUSDT',
      'ETHUSDT',
      'SOLUSDT',
      'DOGEUSDT',
      'BNBUSDT',
      'XRPUSDT',
      'SUIUSDT',
      'AVAXUSDT',
      'NEARUSDT',
      'LINKUSDT',
      'APTUSDT',
      'ADAUSDT',
    ]
    const presentSymbols = new Set(positions.map((p) => p.symbol))
    const ordered = canonicalOrder.filter((s) => presentSymbols.has(s))
    positions.forEach((p) => {
      if (!ordered.includes(p.symbol)) ordered.push(p.symbol)
    })
    return ordered.length > 0 ? ordered : canonicalOrder
  }, [positions])

  const evaluatedPairs = useMemo(() => {
    return allSymbols.map((symbol) => {
      const pos = positionMap.get(symbol)
      const ticker = tickerMap.get(symbol)
      const ictSig = ictSignals ? ictSignals[symbol] : undefined
      const entry = evaluatePairEntry(symbol, pos, ictSig, scalperCriteria, btcMacroTrend)
      const price = ticker?.lastPrice || pos?.currentPrice || 0
      const markPrice = ticker?.markPrice || pos?.markPrice || price
      const fundingRate = ticker?.fundingRate ?? 0.0001
      const basisPct = ticker?.basisPct ?? 0

      return {
        symbol,
        cleanSymbol: symbol.replace(/USDT$/, ''),
        pos,
        ticker,
        entry,
        price,
        markPrice,
        fundingRate,
        basisPct,
      }
    })
  }, [allSymbols, positionMap, tickerMap, ictSignals, scalperCriteria, btcMacroTrend])

  const activeEntryCount = evaluatedPairs.filter(
    (p) => p.entry.type === 'DUAL' || p.entry.type === 'ICT' || p.entry.type === 'SCALPER',
  ).length

  const handleCardClick = (symbol: string) => {
    if (onSelectPair) {
      onSelectPair(symbol)
    } else {
      window.location.hash = `#/pair/${symbol}`
    }
  }

  return (
    <section
      className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden"
      data-testid="pair-price-tickers-card"
      aria-label="Live Pair Price Tickers"
    >
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />

      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-white/[0.06] mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.15)]">
            <Radio className="w-5 h-5 text-cyan-400 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Live Pair Tickers &amp; Opportunity Radar
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-300">
                12 Perpetual Pairs
              </span>
              {activeEntryCount > 0 ? (
                <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 animate-pulse">
                  {activeEntryCount} Entry Signal{activeEntryCount > 1 ? 's' : ''} Active
                </span>
              ) : (
                <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-zinc-800/80 border border-white/[0.08] text-zinc-400">
                  All 12 Standby / Scanning
                </span>
              )}
              <ProvenanceBadge source="LIVE EXCHANGE" />
            </div>
            <p className="text-xs text-zinc-400 mt-0.5">
              Live Binance Futures streaming prices. Click any ticker card to open full terminal with chart, ICT Twins breakdown &amp; scalper signals.
            </p>
          </div>
        </div>
      </div>

      {/* 12-Pair Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
        {evaluatedPairs.map(
          ({ symbol, cleanSymbol, entry, price, markPrice, fundingRate, basisPct, pos }) => {
            const isEntryActive =
              entry.type === 'DUAL' || entry.type === 'ICT' || entry.type === 'SCALPER'
            const isLong = pos?.state === 'LONG'
            const isShort = pos?.state === 'SHORT'
            const hasPosition = isLong || isShort

            return (
              <div
                key={symbol}
                onClick={() => handleCardClick(symbol)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleCardClick(symbol)
                  }
                }}
                tabIndex={0}
                role="button"
                aria-label={`Open details for ${symbol}`}
                data-testid={`pair-ticker-card-${symbol.toLowerCase()}`}
                className={`group relative p-4 rounded-xl transition-all duration-200 cursor-pointer border text-left outline-none ${
                  isEntryActive
                    ? 'bg-cyan-950/20 hover:bg-cyan-900/30 border-cyan-500/40 hover:border-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.12)]'
                    : 'bg-[#0e1320]/70 hover:bg-[#141b2e]/80 border-white/[0.06] hover:border-cyan-500/30 hover:shadow-lg'
                }`}
              >
                {/* Top Row: Symbol & Entry Status Badge */}
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-cyan-400 group-hover:scale-125 transition-transform" />
                    <span className="font-bold text-sm tracking-wide text-white group-hover:text-cyan-300 transition-colors">
                      {cleanSymbol}
                    </span>
                    <span className="text-[10px] font-mono text-zinc-500 uppercase">USDT</span>
                  </div>

                  {/* Dynamic Entry Badge */}
                  <span
                    className={`text-[10px] font-mono font-semibold py-0.5 px-2 rounded-md border tracking-tight ${entry.badgeClass}`}
                    data-testid={`pair-entry-badge-${symbol.toLowerCase()}`}
                  >
                    {entry.badgeLabel}
                  </span>
                </div>

                {/* Price Display */}
                <div className="flex items-baseline justify-between gap-2 mb-2.5">
                  <div>
                    <div className="text-xl font-bold font-mono text-white tracking-tight">
                      ${formatPrice(price)}
                    </div>
                    <div className="text-[10px] font-mono text-zinc-400 mt-0.5">
                      Mark: ${formatPrice(markPrice)}
                    </div>
                  </div>

                  {/* 24h change / basis indicator */}
                  <div className="text-right">
                    <span
                      className={`inline-flex items-center text-xs font-mono font-semibold ${
                        basisPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      {basisPct >= 0 ? (
                        <TrendingUp size={12} className="mr-0.5" />
                      ) : (
                        <TrendingDown size={12} className="mr-0.5" />
                      )}
                      {basisPct >= 0 ? `+${basisPct.toFixed(2)}%` : `${basisPct.toFixed(2)}%`}
                    </span>
                    <div className="text-[10px] font-mono text-zinc-500">
                      FR: {(fundingRate * 100).toFixed(4)}%
                    </div>
                  </div>
                </div>

                {/* Position or Standby Footer */}
                <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-[11px] text-zinc-400">
                  <div>
                    {hasPosition ? (
                      <span
                        className={`font-mono font-semibold px-1.5 py-0.5 rounded text-[10px] ${
                          isLong
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                        }`}
                      >
                        {isLong ? '🟢 LONG' : '🔴 SHORT'} (${pos?.notionalUsdt.toFixed(2)})
                      </span>
                    ) : entry.type !== 'STANDBY' ? (
                      <span className="text-purple-300 font-mono font-semibold text-[10px]">
                        Signal ({entry.side === 'SELL' ? 'SHORT BIAS' : 'LONG BIAS'}) • 0.00 Exp
                      </span>
                    ) : (
                      <span className="text-zinc-500 text-[10px] font-mono">
                        {pos?.state || 'SCANNING / STANDBY'} • NEUTRAL • 0.00 Exposure
                      </span>
                    )}
                  </div>

                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-400 group-hover:translate-x-0.5 transition-transform">
                    <span>Terminal</span>
                    <ChevronRight size={13} />
                  </span>
                </div>
              </div>
            )
          },
        )}
      </div>
    </section>
  )
}
