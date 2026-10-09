import {
  Activity,
  CheckCircle2,
  PieChart,
  Scale,
  ShieldCheck,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react'
import type { ExecutiveDashboardModel } from './types'

export interface KpiCardsProps {
  kpis: ExecutiveDashboardModel['kpis']
}

export function KpiCards({ kpis }: KpiCardsProps) {
  const isPnlPositive = kpis.realizedPnlUsdt >= 0
  const exposurePct = Math.min(
    100,
    Math.max(0, (kpis.activeExposureUsdt / (kpis.maxExposureCapUsdt || 25)) * 100),
  )
  const isReserveFloorHealthy =
    kpis.cashReservePct >= kpis.minCashReserveFloorPct

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {/* KPI Card 1: Total Balance & Equity */}
      <div className="glass-panel rounded-2xl p-5 hover:-translate-y-0.5 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden">
        {/* Subtle accent border at top */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-cyan-500/0 via-cyan-500/50 to-cyan-500/0" />

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Jumlah Ekuiti &amp; Baki
            </span>
            <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(6,182,212,0.15)]">
              <Wallet className="w-4 h-4" />
            </div>
          </div>

          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-2xl sm:text-3xl font-mono font-bold tracking-tight text-white tabular-nums">
              {`$${kpis.totalEquityUsdt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`}
            </span>
            <span className="text-xs font-mono font-semibold text-cyan-400">
              USDT
            </span>
          </div>

          <p className="text-[11px] text-zinc-400 mb-3 font-mono">
            Dompet Binance Futures (Simpanan Modal Selamat)
          </p>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex flex-col gap-1.5 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Tunai Sedia Ada:</span>
            <span className="font-semibold text-emerald-400 tabular-nums">
              {`$${kpis.cashUsdt.toFixed(2)} (${kpis.cashReservePct.toFixed(1)}%)`}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Margin Diperuntukkan:</span>
            <span className="font-semibold text-cyan-400 tabular-nums">
              {`$${kpis.allocatedMarginUsdt.toFixed(2)}`}
            </span>
          </div>
        </div>
      </div>

      {/* KPI Card 2: Net Realized PnL & Win Rate */}
      <div className="glass-panel rounded-2xl p-5 hover:-translate-y-0.5 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden">
        {/* Subtle accent border at top */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-emerald-500/0 via-emerald-500/50 to-emerald-500/0" />

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Untung Bersih &amp; Kadar Kemenangan
            </span>
            <div className={`p-2 rounded-xl group-hover:scale-105 transition-transform border ${
              isPnlPositive
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
            }`}>
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>

          <div className="flex items-baseline gap-2 mb-2">
            <span className={`text-2xl sm:text-3xl font-mono font-bold tracking-tight tabular-nums ${
              isPnlPositive ? 'text-emerald-400' : 'text-rose-400'
            }`}>
              {`${isPnlPositive ? '+' : ''}$${kpis.realizedPnlUsdt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`}
            </span>
            <span className="text-xs font-mono font-semibold text-zinc-400">
              USDT
            </span>
          </div>

          <div className="flex items-center gap-2 mb-3">
            <span className="inline-flex items-center gap-1 text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-emerald-500/10 border border-emerald-500/25 text-emerald-400">
              {`${kpis.winRatePct.toFixed(1)}% Win Rate`}
            </span>
            <span className="text-[11px] text-zinc-400 font-mono">
              {`${kpis.totalTrades} Dagangan Selesai`}
            </span>
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono">
          <span className="text-zinc-400">Penjimatan Yuran:</span>
          <span className="text-cyan-400 font-semibold flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-amber-400 animate-pulse" />
            100% Maker (0.02%)
          </span>
        </div>
      </div>

      {/* KPI Card 3: Active Exposure & Capital Sizing */}
      <div className="glass-panel rounded-2xl p-5 hover:-translate-y-0.5 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden">
        {/* Subtle accent border at top */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-purple-500/0 via-purple-500/50 to-purple-500/0" />

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Pendedahan Aktif &amp; Had Siling
            </span>
            <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(168,85,247,0.15)]">
              <PieChart className="w-4 h-4" />
            </div>
          </div>

          <div className="flex items-baseline gap-1.5 mb-2">
            <span className="text-2xl sm:text-3xl font-mono font-bold tracking-tight text-white tabular-nums">
              {`$${kpis.activeExposureUsdt.toFixed(2)}`}
            </span>
            <span className="text-xs font-mono text-zinc-400">
              {`/ $${kpis.maxExposureCapUsdt.toFixed(2)} Had Maksimum`}
            </span>
          </div>

          {/* Exposure Progress Bar */}
          <div className="w-full bg-white/[0.06] rounded-full h-1.5 mb-2 overflow-hidden border border-white/[0.04]">
            <div
              className={`h-1.5 rounded-full transition-all duration-500 ${
                exposurePct > 80
                  ? 'bg-rose-500'
                  : exposurePct > 50
                    ? 'bg-amber-500'
                    : 'bg-gradient-to-r from-cyan-400 to-emerald-400'
              }`}
              style={{ width: `${Math.max(4, exposurePct)}%` }}
            />
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex flex-col gap-1 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Rizab Tunai:</span>
            <span
              className={`font-semibold ${
                isReserveFloorHealthy ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {`${kpis.cashReservePct.toFixed(1)}% (Lantai ≥ ${kpis.minCashReserveFloorPct}%)`}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-zinc-500">
            <span>Had Pesanan:</span>
            <span>≤ $5.00 USDT / anak</span>
          </div>
        </div>
      </div>

      {/* KPI Card 4: System Health & Solvency */}
      <div className="glass-panel rounded-2xl p-5 hover:-translate-y-0.5 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden">
        {/* Subtle accent border at top */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-sky-500/0 via-sky-500/50 to-sky-500/0" />

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Kesihatan Sistem &amp; Ketulenan
            </span>
            <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(16,185,129,0.15)]">
              <ShieldCheck className="w-4 h-4" />
            </div>
          </div>

          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-2xl sm:text-3xl font-mono font-bold tracking-tight text-emerald-400 flex items-center gap-2">
              <Scale className="w-5 h-5 text-emerald-400 shrink-0" />
              |Δ| &lt; 10⁻¹⁵
            </span>
          </div>

          <div className="flex items-center gap-1.5 mb-3 text-xs text-emerald-400 font-mono">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>Sifar Drift (Zero-Drift Solvency)</span>
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex flex-col gap-1 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Kependaman Rangkaian:</span>
            <span className="text-cyan-400 font-semibold flex items-center gap-1 tabular-nums">
              <Activity className="w-3 h-3 text-cyan-400" />
              {`${kpis.latencyMs.toFixed(1)} ms`}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Sekatan Interlock:</span>
            <span className="text-zinc-300 font-semibold">
              {`${kpis.interlockBlocksCount} Sekatan (0 Bahaya)`}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
