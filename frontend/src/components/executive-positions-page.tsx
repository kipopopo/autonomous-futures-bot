import {
  ArrowDownRight,
  ArrowUpRight,
  Crosshair,
  Gauge,
  Radio,
  Shield,
  Target,
} from 'lucide-react'
import type { BracketPositionsModel, LiveMarketModel } from '@/lib/canary'
import type { PositionTelemetry } from './mission-control/types'

export interface ExecutivePositionsPageProps {
  positions: PositionTelemetry[]
  bracketPositionsModel: BracketPositionsModel
  liveMarketModel: LiveMarketModel
}

export function ExecutivePositionsPage({
  positions,
  bracketPositionsModel,
  liveMarketModel: _liveMarketModel,
}: ExecutivePositionsPageProps) {
  const activeCount = positions.filter((p) => p.state !== 'SCANNING / STANDBY').length

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
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-white">
                  Pasaran &amp; Posisi Terperinci
                </h1>
                <span className="badge badge-sm font-mono font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                  {activeCount} Terbuka / {positions.length} Dipantau
                </span>
              </div>
              <p className="text-xs text-white/50">
                Pemantauan telemetri kedudukan pasaran abadi Binance Futures, pesanan kurungan ATR, dan kedalaman harga tanda
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="badge badge-sm font-mono font-semibold py-1 px-3 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              1.66:1 R:R Sasaran
            </span>
            <span className="badge badge-sm badge-outline font-mono border-white/20 text-white/70">
              Siling $5.00/Pesanan
            </span>
          </div>
        </div>
      </div>

      {/* Main Multi-Asset Positions Table */}
      <div className="glass-panel p-5 relative">
        <h2 className="text-base font-bold tracking-tight text-white mb-4 flex items-center gap-2">
          <Crosshair className="w-4 h-4 text-cyan-400" />
          Kedudukan &amp; Sasaran Semasa Staged Assets
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {positions.map((pos) => {
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
                    <div className="flex justify-between">
                      <span className="text-base-content/60">Harga Tanda:</span>
                      <span className="font-bold text-base-content">
                        ${pos.currentPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-base-content/60">Harga Masuk:</span>
                      <span className="text-base-content font-semibold">
                        {pos.entryPrice > 0
                          ? `$${pos.entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                          : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-base-content/60">Saiz / Notional:</span>
                      <span className="text-base-content">
                        {pos.size} (${pos.notionalUsdt.toFixed(2)} USDT)
                      </span>
                    </div>
                    <div className="flex justify-between pt-1 border-t border-base-300/60">
                      <span className="text-base-content/60">PnL Semasa:</span>
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
                      ${pos.takeProfitPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between text-rose-400">
                    <span className="flex items-center gap-1">
                      <Shield className="w-3.5 h-3.5" /> SL 1.2x ATR:
                    </span>
                    <span className="font-semibold">
                      ${pos.stopLossPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}
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
            Pesanan Kurungan Dinamik (Dynamic Trailing Stop Brackets)
          </h3>

          <div className="overflow-x-auto">
            <table className="table table-sm w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-white/[0.08] text-white/50 text-[11px] uppercase">
                  <th>ID Kurungan</th>
                  <th>Pasangan</th>
                  <th>Jenis Kurungan</th>
                  <th>Harga Masuk</th>
                  <th>Harga Pencetus (TP/SL)</th>
                  <th>Ratchet Watermark</th>
                  <th>Kadar Callback</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {bracketPositionsModel.brackets.length > 0 ? (
                  bracketPositionsModel.brackets.map((b) => (
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
                      Tiada kurungan aktif pada masa ini.
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
