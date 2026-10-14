import {
  AlertTriangle,
  CheckCircle2,
  PieChart,
  Scale,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import type {
  ProductionLaunchModel,
  RiskModel,
  KillSwitchModel,
  ExecutionStatusResponse,
  MicrostructureModel,
  LiveMarketModel,
} from '@/lib/canary'

export interface ExecutiveSafetyPageProps {
  productionLaunchModel: ProductionLaunchModel
  riskModel: RiskModel
  killSwitchModel: KillSwitchModel
  executionStatus?: ExecutionStatusResponse | null
  microstructureModel?: MicrostructureModel | null
  liveMarketModel?: LiveMarketModel | null
  latencyMs?: number
}

function finiteValue(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatUsdt(value: number | null, digits = 4): string {
  return value === null ? 'Unknown' : `$${value.toFixed(digits)} USDT`
}

export function ExecutiveSafetyPage({
  riskModel,
  killSwitchModel,
  executionStatus,
  microstructureModel,
  liveMarketModel,
  latencyMs,
}: ExecutiveSafetyPageProps) {
  const liveSolvency = executionStatus?.solvency
  const dailyRisk = executionStatus?.daily_risk
  const wallet = finiteValue(liveSolvency?.cash_usdt)
  const availableBalance = finiteValue(liveSolvency?.available_balance_usdt)
  const availablePct = finiteValue(liveSolvency?.cash_reserve_pct)
  const allocatedMargin = finiteValue(liveSolvency?.allocated_margin_usdt)
  const unrealizedPnl = finiteValue(liveSolvency?.unrealized_pnl_usdt)
  const startingEquity = finiteValue(liveSolvency?.starting_equity_usdt)
  const realizedPnl = finiteValue(liveSolvency?.realized_pnl_usdt)
  const totalEquity = finiteValue(liveSolvency?.total_equity_usdt)
  const drift = finiteValue(liveSolvency?.drift_usdt)
  const ledgerVerified =
    executionStatus?.verified === true &&
    liveSolvency?.zero_balance_drift_verified === true &&
    drift !== null &&
    Math.abs(drift) < 1e-15

  const dailyLoss =
    dailyRisk?.verified === true
      ? finiteValue(dailyRisk.loss_usdt ?? executionStatus?.intra_day_loss_usdt)
      : null
  const dailyLimit =
    dailyRisk?.verified === true ? finiteValue(dailyRisk.limit_usdt) : null
  const dailyLimitPct =
    dailyRisk?.verified === true ? finiteValue(dailyRisk.limit_pct) : null
  const dayStartEquity =
    dailyRisk?.verified === true ? finiteValue(dailyRisk.day_start_equity_usdt) : null
  const dailyRiskVerified =
    dailyRisk?.verified === true &&
    dailyLoss !== null &&
    dailyLimit !== null &&
    dailyLimitPct !== null &&
    dayStartEquity !== null
  const dailyBreached =
    dailyRiskVerified &&
    (dailyRisk?.breached === true || (dailyLoss ?? 0) >= (dailyLimit ?? Infinity))

  const hasMicrostructureEvidence = (microstructureModel?.snapshots.length ?? 0) > 0
  const spectralRadius = hasMicrostructureEvidence
    ? finiteValue(microstructureModel?.maxSpectralRadius)
    : null
  const latency =
    [
      finiteValue(latencyMs),
      finiteValue(liveMarketModel?.gatewayHealth?.latency_ms),
      finiteValue(riskModel.latestHeartbeat?.latency_ms),
    ].find((value) => value !== null && value > 0) ?? null

  const knownTripwires = [
    spectralRadius === null ? null : spectralRadius >= 1,
    latency === null ? null : latency > 500,
    dailyRiskVerified ? dailyBreached : null,
  ]
  const activeTripwires = knownTripwires.filter((state) => state === true).length
  const unknownTripwires = knownTripwires.filter((state) => state === null).length
  const accountStatus = executionStatus?.status ?? 'LIVE ACCOUNT EVIDENCE UNAVAILABLE'
  const dailyStatus = !dailyRiskVerified
    ? 'UNVERIFIED'
    : dailyBreached
      ? 'LOSS LIMIT REACHED'
      : 'WITHIN LIMIT'
  const dailyStatusClass = !dailyRiskVerified
    ? 'text-amber-300'
    : dailyBreached
      ? 'text-rose-400'
      : 'text-emerald-400'

  return (
    <div className="w-full space-y-6">
      <div className="glass-panel p-5 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-bold tracking-tight text-white">
                  Risk Controls &amp; Ledger Integrity
                </h1>
                <span
                  className={`badge badge-sm font-mono font-semibold border ${ledgerVerified ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/15 text-amber-200 border-amber-500/30'}`}
                >
                  {ledgerVerified ? 'ACCOUNT LEDGER VERIFIED' : 'ACCOUNT LEDGER UNVERIFIED'}
                </span>
              </div>
              <p className="text-xs text-white/50">
                Exchange account reconciliation, available margin, dynamic daily-loss control, and observed tripwires.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="badge badge-sm badge-outline font-mono text-white/80 border-white/20">
              {accountStatus}
            </span>
            <span
              className={`badge badge-sm font-mono border ${activeTripwires > 0 ? 'text-rose-300 border-rose-500/40 bg-rose-500/10' : unknownTripwires > 0 ? 'text-amber-200 border-amber-500/40 bg-amber-500/10' : 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'}`}
            >
              {`${activeTripwires} observed tripwires · ${unknownTripwires} unknown`}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="glass-card-subtle p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-white/70">Double-Entry Invariant</span>
              <Scale className="w-4 h-4 text-cyan-300" />
            </div>
            <div className={`text-xl font-mono font-bold my-1 ${ledgerVerified ? 'text-emerald-400' : 'text-amber-200'}`}>
              {ledgerVerified ? 'Verified' : 'Unverified'}
            </div>
            <p className="text-xs text-white/50">
              Wallet and equity reconcile against fresh authenticated exchange evidence with |Δ| &lt; 10⁻¹⁵ USDT.
            </p>
          </div>
          <div className="mt-3 pt-2 border-t border-white/[0.06] text-[11px] font-mono flex items-center gap-1">
            {ledgerVerified ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : <AlertTriangle className="w-3.5 h-3.5 text-amber-300" />}
            <span className={ledgerVerified ? 'text-emerald-400' : 'text-amber-200'}>
              {ledgerVerified ? 'Zero drift verified' : 'Fresh reconciled evidence required'}
            </span>
          </div>
        </div>

        <div className="glass-card-subtle p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-white/70">Open Position Exposure</span>
              <PieChart className="w-4 h-4 text-cyan-300" />
            </div>
            <div className="text-xl font-mono font-bold text-white my-1">
              {formatUsdt(finiteValue(executionStatus?.aggregate_exposure_usdt), 2)}
            </div>
            <p className="text-xs text-white/50">
              Current exchange-reported position notional; no fixed aggregate exposure ceiling is configured.
            </p>
          </div>
          <div className="mt-3 pt-2 border-t border-white/[0.06] text-[11px] font-mono text-cyan-300 flex items-center gap-1">
            <Zap className="w-3.5 h-3.5" />
            {`${formatUsdt(allocatedMargin, 2)} initial margin in use`}
          </div>
        </div>

        <div className="glass-card-subtle p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-white/70">Exchange Available Margin</span>
              <Shield className="w-4 h-4 text-cyan-300" />
            </div>
            <div className="text-xl font-mono font-bold text-white my-1">
              {formatUsdt(availableBalance, 2)}
            </div>
            <p className="text-xs text-white/50">
              {availablePct === null
                ? 'Availability percentage is unknown without fresh account evidence.'
                : `${availablePct.toFixed(1)}% of current equity is exchange-reported as available; no reserve floor applies.`}
            </p>
          </div>
          <div className="mt-3 pt-2 border-t border-white/[0.06] text-[11px] font-mono text-cyan-300 flex items-center gap-1">
            {availableBalance === null ? 'Exchange balance unavailable' : 'Exchange balance observed'}
          </div>
        </div>

        <div className="glass-card-subtle p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-white/70">Daily Loss Limit</span>
              <AlertTriangle className="w-4 h-4 text-amber-300" />
            </div>
            <div className="text-xl font-mono font-bold text-white my-1">
              {dailyRiskVerified
                ? `${formatUsdt(dailyLoss, 2)} / ${formatUsdt(dailyLimit, 2)}`
                : 'Unknown / Unknown'}
            </div>
            <p className="text-xs text-white/50">
              {dailyRiskVerified
                ? `${dailyLimitPct}% of ${formatUsdt(dayStartEquity, 2)} UTC day-start equity.`
                : 'Requires verified UTC day-start account equity and current risk evidence.'}
            </p>
          </div>
          <div className={`mt-3 pt-2 border-t border-white/[0.06] text-[11px] font-mono flex items-center gap-1 ${dailyStatusClass}`}>
            {dailyStatus}
          </div>
        </div>
      </div>

      <div className="glass-panel p-5 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />
        <h2 className="text-base font-bold text-white mb-4 flex items-center gap-2">
          <Scale className="w-4 h-4 text-cyan-300" />
          Double-Entry Account Reconciliation
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
          <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block mb-1">Wallet Identity:</span>
            <div className="font-bold text-white text-sm mb-2">Wallet = Starting Equity + Net Realized PnL</div>
            <div className="text-[11px] text-white/70 space-y-1">
              <div>Starting equity: {formatUsdt(startingEquity)}</div>
              <div>Net realized PnL: {formatUsdt(realizedPnl)}</div>
              <div className="pt-1 border-t border-white/[0.08] font-bold text-cyan-300">Wallet: {formatUsdt(wallet)}</div>
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block mb-1">Equity Identity:</span>
            <div className="font-bold text-white text-sm mb-2">Equity = Wallet + Unrealized PnL</div>
            <div className="text-[11px] text-white/70 space-y-1">
              <div>Wallet: {formatUsdt(wallet)}</div>
              <div>Unrealized PnL: {formatUsdt(unrealizedPnl)}</div>
              <div className="pt-1 border-t border-white/[0.08] font-bold text-cyan-300">Equity: {formatUsdt(totalEquity)}</div>
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block mb-1">Reconciliation Drift:</span>
            <div className={`font-bold text-sm mb-2 flex items-center gap-1 ${ledgerVerified ? 'text-emerald-400' : 'text-amber-200'}`}>
              {ledgerVerified ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
              {drift === null ? 'Drift: Unknown' : `|Δ| = ${Math.abs(drift).toFixed(15)} USDT`}
            </div>
            <p className="text-[11px] text-white/60 leading-relaxed">
              {ledgerVerified
                ? 'Fresh account evidence confirms wallet and equity drift below 10⁻¹⁵ USDT.'
                : 'The zero-drift invariant is not proven until fresh account and ledger evidence reconcile.'}
            </p>
          </div>
        </div>
      </div>

      <div className="glass-panel p-5 font-mono text-xs relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-amber-500/40 to-transparent" />
        <h2 className="text-base font-bold text-white mb-4 flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-amber-300" />
          Circuit Breaker Evidence
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block text-[11px]">Hawkes Hazard</span>
            <div className="font-bold text-white mt-1">ρ ≥ 1.000</div>
            <span className={`text-[10px] ${spectralRadius === null ? 'text-amber-200' : spectralRadius < 1 ? 'text-emerald-400' : 'text-rose-400'} mt-1 block`}>
              {spectralRadius === null ? 'Status: UNVERIFIED' : `Status: ${spectralRadius < 1 ? 'NORMAL' : 'ELEVATED / CRITICAL'} (ρ = ${spectralRadius.toFixed(3)})`}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block text-[11px]">Gateway Latency</span>
            <div className="font-bold text-white mt-1">Latency &gt; 500 ms</div>
            <span className={`text-[10px] ${latency === null ? 'text-amber-200' : latency <= 500 ? 'text-emerald-400' : 'text-rose-400'} mt-1 block`}>
              {latency === null ? 'Status: UNVERIFIED' : `Status: ${latency <= 500 ? 'NORMAL' : 'HIGH LATENCY'} (${latency.toFixed(1)} ms)`}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block text-[11px]">Daily Loss Guard</span>
            <div className="font-bold text-white mt-1">{dailyRiskVerified ? `${dailyLimitPct}% of day-start equity` : '5% of day-start equity'}</div>
            <span className={`text-[10px] ${dailyStatusClass} mt-1 block`}>Status: {dailyStatus}</span>
          </div>

          <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06]">
            <span className="text-white/50 block text-[11px]">Kill-Switch Evidence</span>
            <div className="font-bold text-white mt-1">Emergency flatten &amp; cancel</div>
            <span className={`text-[10px] ${killSwitchModel.verified ? 'text-cyan-300' : 'text-amber-200'} mt-1 block`}>
              {killSwitchModel.verified ? `Reported state: ${killSwitchModel.killSwitchState}` : 'Status: UNVERIFIED'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
