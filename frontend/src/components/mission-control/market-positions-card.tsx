import {
  ArrowDownRight,
  ArrowUpRight,
  Crosshair,
  Gauge,
  Radio,
  Shield,
  Target,
} from 'lucide-react'
import type { PositionTelemetry } from './types'

export interface MarketPositionsCardProps {
  positions: PositionTelemetry[]
}

export function MarketPositionsCard({ positions }: MarketPositionsCardProps) {
  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent" />

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.15)]">
            <Radio className="w-5 h-5 text-cyan-400 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Pasaran Langsung &amp; Posisi Aktif
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-400">
                SOL · ETH · BTC
              </span>
            </div>
            <p className="text-xs text-zinc-400">
              Pengawasan harga tanda (mark price), kedudukan terbuka, dan sasaran kurungan TP/SL berpandukan ATR
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-semibold py-1 px-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.1)]">
            1.66 : 1 Nisbah R:R
          </span>
          <span className="inline-flex items-center gap-1 text-xs font-mono py-1 px-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-zinc-300">
            Maker 0.02% Fee Drag
          </span>
        </div>
      </div>

      {/* Grid of 3 Staged Pairs */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {positions.map((pos) => {
          const isScanning = pos.state === 'SCANNING / STANDBY'
          const isLong = pos.state === 'LONG'
          const isShort = pos.state === 'SHORT'
          const pnlPositive = pos.unrealizedPnlUsdt >= 0

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
                      Harga Tanda (Mark):
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
                      <span className="leading-snug">Mengimbas kecairan 15m (Capitulation Sweep)...</span>
                    </div>
                  ) : (
                    <div className="p-3 rounded-lg bg-black/25 border border-white/[0.06] mt-2 flex flex-col gap-1.5 text-xs font-mono">
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Harga Masuk:</span>
                        <span className="font-semibold text-white tabular-nums">
                          ${pos.entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Saiz / Nilai:</span>
                        <span className="font-semibold text-white tabular-nums">
                          {pos.size} (${pos.notionalUsdt.toFixed(2)} USDT)
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-400">Margin Terkunci:</span>
                        <span className="font-semibold text-cyan-400 tabular-nums">
                          ${pos.marginUsdt.toFixed(2)} USDT (1x)
                        </span>
                      </div>
                      <div className="flex items-center justify-between pt-1.5 border-t border-white/[0.06]">
                        <span className="text-zinc-400">PnL Belum Direalisasi:</span>
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
                    <span>Ambil Untung (TP 2.0x ATR):</span>
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
                    <span>Henti Rugi (SL 1.2x ATR):</span>
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
                <div className="w-full bg-white/[0.05] rounded-full h-1.5 my-1 relative overflow-hidden border border-white/[0.04]">
                  <div
                    className="absolute left-0 top-0 bottom-0 bg-rose-500/60"
                    style={{ width: '30%' }}
                  />
                  <div
                    className="absolute left-[30%] top-0 bottom-0 bg-cyan-400"
                    style={{ width: '10%' }}
                  />
                  <div
                    className="absolute right-0 top-0 bottom-0 bg-emerald-500/60"
                    style={{ width: '60%' }}
                  />
                </div>

                {/* Distance Meter Gauge */}
                <div className="flex items-center justify-between text-[11px] text-zinc-500 pt-0.5">
                  <span className="flex items-center gap-1 text-zinc-400">
                    <Gauge className="w-3 h-3 text-cyan-400" />
                    Nisbah Risiko/Ganjaran:
                  </span>
                  <span className="font-mono font-bold text-zinc-300 py-0.5 px-1.5 rounded bg-white/[0.05] border border-white/[0.08]">
                    {pos.riskRewardRatio}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
