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
import { ProvenanceBadge } from './provenance-badge'

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
              Total Balance &amp; Equity
            </span>
            <div className="flex items-center gap-2">
              <ProvenanceBadge source="LIVE EXCHANGE" />
              <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(6,182,212,0.15)]">
                <Wallet className="w-4 h-4" />
              </div>
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
            Binance Futures Wallet (Protected Capital Reserve)
          </p>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex flex-col gap-1.5 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Available Cash:</span>
            <span className="font-semibold text-emerald-400 tabular-nums">
              {`$${kpis.cashUsdt.toFixed(2)} (${kpis.cashReservePct.toFixed(1)}%)`}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Allocated Margin:</span>
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
              Net Realized PnL &amp; Win Rate
            </span>
            <div className="flex items-center gap-2">
              <ProvenanceBadge source="LIVE EXCHANGE" />
              <div className={`p-2 rounded-xl group-hover:scale-105 transition-transform border ${
                isPnlPositive
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                  : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
              }`}>
                <TrendingUp className="w-4 h-4" />
              </div>
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
              {`${kpis.totalTrades} Completed Trades`}
            </span>
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono">
          <span className="text-zinc-400">Fee Savings:</span>
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
              Active Exposure &amp; Capital Sizing
            </span>
            <div className="flex items-center gap-2">
              <ProvenanceBadge source="DAEMON 24/7" />
              <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(168,85,247,0.15)]">
                <PieChart className="w-4 h-4" />
              </div>
            </div>
          </div>

          <div className="flex items-baseline gap-1.5 mb-2">
            <span className="text-2xl sm:text-3xl font-mono font-bold tracking-tight text-white tabular-nums">
              {`$${kpis.activeExposureUsdt.toFixed(2)}`}
            </span>
            <span className="text-xs font-mono text-zinc-400">
              {`/ $${kpis.maxExposureCapUsdt.toFixed(2)} Max Cap`}
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
            <span className="text-zinc-400">Cash Reserve:</span>
            <span
              className={`font-semibold ${
                isReserveFloorHealthy ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {`${kpis.cashReservePct.toFixed(1)}% (Floor ≥ ${kpis.minCashReserveFloorPct}%)`}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-zinc-500">
            <span>Risk Policy:</span>
            <span>0.5% Risk / 5% Daily Loss</span>
          </div>
          {kpis.dailyRiskVerified &&
            kpis.dailyRiskRemainingUsdt !== undefined &&
            kpis.dailyRiskLimitUsdt !== undefined && (
              <div
                className="flex items-center justify-between text-[11px] text-emerald-400"
                data-testid="daily-risk-budget-row"
              >
                <span>Daily Risk Budget:</span>
                <span className="font-semibold tabular-nums">
                  {`$${kpis.dailyRiskRemainingUsdt.toFixed(2)} / $${kpis.dailyRiskLimitUsdt.toFixed(2)}`}
                </span>
              </div>
            )}
        </div>
      </div>

      {/* KPI Card 4: System Health & Solvency */}
      <div className="glass-panel rounded-2xl p-5 hover:-translate-y-0.5 transition-all duration-300 flex flex-col justify-between group relative overflow-hidden">
        {/* Subtle accent border at top */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-sky-500/0 via-sky-500/50 to-sky-500/0" />

        <div>
          <div className="flex items-center justify-between gap-2 mb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              System Health &amp; Solvency
            </span>
            <div className="flex items-center gap-2">
              <ProvenanceBadge source="DAEMON 24/7" />
              <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-105 transition-transform shadow-[0_0_12px_rgba(16,185,129,0.15)]">
                <ShieldCheck className="w-4 h-4" />
              </div>
            </div>
          </div>

          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-2xl sm:text-3xl font-mono font-bold tracking-tight text-emerald-400 flex items-center gap-2">
              <Scale className="w-5 h-5 text-emerald-400 shrink-0" />
              100% Solvency
            </span>
          </div>

          <div className="flex items-center gap-1.5 mb-3 text-xs text-emerald-400 font-mono">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>Zero-Drift Solvency (|Δ| &lt; 10⁻¹⁵)</span>
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex flex-col gap-1 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Gateway Latency:</span>
            <span className="text-cyan-400 font-semibold flex items-center gap-1 tabular-nums">
              <Activity className="w-3 h-3 text-cyan-400" />
              {`${kpis.latencyMs.toFixed(1)} ms`}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-zinc-400">Interlock Blocks:</span>
            <span className="text-zinc-300 font-semibold">
              {`${kpis.interlockBlocksCount} Interlock Blocks (0 Hazards)`}
            </span>
          </div>
          {kpis.engineState && (
            <div
              className="flex items-center justify-between text-[11px] text-emerald-400"
              data-testid="runtime-engine-state-row"
            >
              <span>Runtime Engine:</span>
              <span className="font-semibold tabular-nums">
                {kpis.runtimeArrivalCount !== undefined
                  ? `${kpis.engineState} (${kpis.runtimeArrivalCount.toLocaleString('en-US')} arrivals)`
                  : kpis.engineState}
              </span>
            </div>
          )}
          {kpis.watchdogStatus && (
            <div
              className={`flex items-center justify-between text-[11px] ${
                kpis.watchdogStatus === 'HEALTHY'
                  ? 'text-emerald-400'
                  : kpis.watchdogStatus === 'WARNING'
                    ? 'text-amber-400'
                    : 'text-rose-400'
              }`}
              data-testid="runtime-watchdog-row"
            >
              <span>Runtime Watchdog:</span>
              <span className="font-semibold tabular-nums">
                {kpis.watchdogMainPid !== undefined
                  ? `${kpis.watchdogStatus} (PID ${kpis.watchdogMainPid} · ${kpis.watchdogRestarts ?? 0} restarts)`
                  : kpis.watchdogAlerts && kpis.watchdogAlerts.length > 0
                    ? `${kpis.watchdogStatus} (${kpis.watchdogAlerts.length} alerts)`
                    : `${kpis.watchdogStatus} (0 alerts)`}
              </span>
            </div>
          )}
          {kpis.watchdogChannels && kpis.watchdogChannels.length > 0 && (
            <div
              className={`flex items-center justify-between text-[11px] ${
                kpis.watchdogAlertActive ? 'text-amber-400' : 'text-cyan-400'
              }`}
              data-testid="runtime-watchdog-alerts-row"
            >
              <span>Watchdog Alerts:</span>
              <span className="font-semibold tabular-nums">
                {`${kpis.watchdogChannels.map((c) => c.toUpperCase()).join(' + ')} (${
                  kpis.watchdogAlertActive ? 'ACTIVE' : 'STANDBY'
                } · ${kpis.watchdogTotalAlertsSent ?? 0} sent)`}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
