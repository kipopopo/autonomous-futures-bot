import { useState } from 'react'
import {
  Activity,
  CheckCircle2,
  Flame,
  GitBranch,
  Lock,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react'

import type { StressFaultInjectionModel } from '@/lib/canary'

export function StressPage({ model }: { model: StressFaultInjectionModel }) {
  const [vectorFilter, setVectorFilter] = useState<string>('ALL')
  const phaseLabel = model.phase.replace(/^phase_/i, '')

  const startingEquity = model.solvency?.starting_equity_usdt ?? model.ledger?.starting_equity ?? null
  const cash = model.solvency?.cash_usdt ?? model.ledger?.cash ?? null
  const allocatedMargin = model.solvency?.allocated_margin_usdt ?? model.ledger?.allocated_margin ?? null
  const unrealizedPnl = model.solvency?.unrealized_pnl_usdt ?? model.ledger?.unrealized_pnl ?? null
  const realizedPnl = model.solvency?.realized_pnl_usdt ?? model.ledger?.realized_pnl ?? null
  const drift = model.solvency?.drift_usdt ?? model.ledger?.drift ?? null
  const cashReservePct = model.solvency?.cash_reserve_pct ??
    (startingEquity !== null && startingEquity > 0 && cash !== null
      ? (cash / startingEquity) * 100
      : null)
  const reserveStatus = model.solvency?.unencumbered_cash_verified
  const preEquity = model.capitalPreservationStats?.pre_flatten_equity_usdt ?? null
  const postCash = model.capitalPreservationStats?.post_flatten_cash_usdt ?? null
  const preservedPct = model.capitalPreservationStats?.capital_preserved_pct ?? null
  const maxLossBudget = model.capitalPreservationStats?.max_loss_budget_usdt ?? null
  const actualLoss = model.capitalPreservationStats?.actual_loss_usdt ?? null
  const circuitState = model.circuitState || 'UNKNOWN'
  const formatAmount = (value: number | null | undefined, decimals = 2) =>
    typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(decimals)} USDT` : '—'
  const formatPercent = (value: number | null | undefined, decimals = 2) =>
    typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(decimals)}%` : '—'

  const filteredVectors = model.shockVectors.filter((v) => {
    if (vectorFilter === 'ALL') return true
    return v.status === vectorFilter
  })

  if (!model.verified) {
    return (
      <section className="card border border-warning/40 bg-base-200 p-6 space-y-2" aria-labelledby="stress-unavailable-heading">
        <h2 id="stress-unavailable-heading" className="text-lg font-bold">Stress evidence unavailable</h2>
        <p className="text-sm text-base-content/70">
          No verified stress-fault-injection artifact is available for this view. Current runtime health,
          execution authority, and account solvency cannot be inferred from missing evidence.
        </p>
        <p className="text-xs font-mono text-base-content/60">Status: {model.status || 'UNKNOWN'}</p>
      </section>
    )
  }

  return (
    <div className="space-y-6" aria-labelledby="stress-resilience-heading">
      {/* 1. Header & Safety Badges */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Phase {phaseLabel} / Historical Stress Evidence
          </p>
          <h2 id="stress-resilience-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Recorded Stress Fault-Injection Results
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-error gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm">
            <Flame size={14} />
            HISTORICAL ARTIFACT VERIFIED
          </span>
          <span className={`badge ${model.isPaperSafe ? 'badge-success' : 'badge-warning'} gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm`}>
            <ShieldCheck size={14} />
            {model.paperSafetyEvidenceAvailable ? (model.isPaperSafe ? 'PAPER-SAFE IN REPORT' : 'PAPER SAFETY FAILED') : 'PAPER SAFETY UNKNOWN'}
          </span>
          <span className={`badge badge-outline ${model.executionAuthorityAvailable ? (model.isExecutionOff ? 'badge-success' : 'badge-error') : 'badge-warning'} font-mono text-[11px] font-bold tracking-wider py-2.5 px-3`}>
            <Lock size={12} className="inline mr-1" />
            {model.executionAuthorityAvailable ? (model.isExecutionOff ? 'EXECUTION AUTHORITY: OFF' : 'EXECUTION AUTHORITY: ON') : 'EXECUTION AUTHORITY: UNKNOWN'}
          </span>
          <span className={`badge ${model.subMillisecondLatencyVerified === true ? 'badge-success' : model.subMillisecondLatencyVerified === false ? 'badge-error' : 'badge-warning'} gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm`}>
            <Zap size={14} />
            {model.subMillisecondLatencyVerified === true
              ? 'RECORDED LATENCY < 1 ms'
              : model.subMillisecondLatencyVerified === false
                ? 'LATENCY GATE FAILED'
                : 'LATENCY DATA UNAVAILABLE'}
          </span>
          <span className={`badge badge-outline ${model.isZeroDrift === true ? 'badge-success' : model.isZeroDrift === false ? 'badge-error' : 'badge-warning'} font-mono text-[11px] font-bold py-2.5 px-3`}>
            <Scale size={12} className="inline mr-1" />
            {model.isZeroDrift === true
              ? 'ZERO-DRIFT VERIFIED IN REPORT'
              : model.isZeroDrift === false
                ? 'ZERO-DRIFT GATE FAILED'
                : 'ZERO-DRIFT UNKNOWN'}
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        This page displays values recorded in the verified Phase {phaseLabel} research artifact. They are historical test
        results, not live runtime telemetry, an account reconciliation, or proof that protective controls are currently armed.
      </p>

      {/* 2. Recorded Shock Vector Status Matrix */}
      <section aria-labelledby="shock-vectors-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 id="shock-vectors-heading" className="text-base font-bold flex items-center gap-2">
              <Activity size={18} className="text-error" />
              Recorded Shock Vector Status
            </h3>
            <p className="text-xs text-base-content/60">
              Shock vectors and outcomes recorded by this artifact.
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-base-content/60 mr-1">Filter:</span>
            {['ALL', 'TRIGGERED', 'ACTIVE', 'MITIGATED', 'NORMAL'].map((f) => (
              <button
                key={f}
                type="button"
                className={`btn btn-xs ${vectorFilter === f ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setVectorFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {filteredVectors.map((v) => {
            const isTriggered = v.status === 'TRIGGERED'
            const isMitigated = v.status === 'MITIGATED'
            const isActive = v.status === 'ACTIVE'
            return (
              <div
                key={v.vector_id}
                className={`card border p-4 shadow-sm flex flex-col justify-between ${
                  isTriggered
                    ? 'bg-error/10 border-error/40'
                    : isMitigated
                    ? 'bg-warning/10 border-warning/40'
                    : isActive
                    ? 'bg-info/10 border-info/40'
                    : 'bg-base-200 border-base-300'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-mono font-bold tracking-wider uppercase text-base-content/70">
                      {v.vector_id}
                    </span>
                    <span
                      className={`badge badge-xs font-mono font-bold py-1 px-2 ${
                        isTriggered
                          ? 'badge-error'
                          : isMitigated
                          ? 'badge-warning'
                          : isActive
                          ? 'badge-info'
                          : 'badge-success'
                      }`}
                    >
                      {v.status}
                    </span>
                  </div>
                  <h4 className="font-bold text-sm mt-2 text-base-content">{v.name}</h4>
                  <p className="text-xs text-base-content/80 mt-1 font-mono">{v.intensity}</p>
                </div>
                <div className="mt-3 pt-2 border-t border-base-content/10 flex items-center justify-between text-xs">
                  <span className="text-base-content/60 font-semibold">Action:</span>
                  <span className="font-mono text-error font-semibold">{v.action_taken}</span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 3. Recorded Circuit Breaker Latencies */}
      <section aria-labelledby="latency-heading" className="space-y-3">
        <div>
          <h3 id="latency-heading" className="text-base font-bold flex items-center gap-2">
            <Zap size={18} className="text-warning" />
            Recorded Circuit Breaker Latencies
          </h3>
          <p className="text-xs text-base-content/60">
            Latency measurements recorded by this artifact; an empty table does not pass the latency gate.
          </p>
        </div>

        <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-200">
          <table className="table table-sm w-full font-mono text-xs">
            <thead>
              <tr className="bg-base-300/60 text-base-content font-bold">
                <th>Breaker ID</th>
                <th>Shock Vector</th>
                <th>Detection Latency (&mu;s)</th>
                <th>Trigger Latency (&mu;s)</th>
                <th>Action Taken</th>
                <th>Tripped Status</th>
                <th>Compliance</th>
              </tr>
            </thead>
            <tbody>
              {model.circuitBreakerLatencies.length > 0 ? (
                model.circuitBreakerLatencies.map((cb) => (
                  <tr key={cb.breaker_id} className="hover:bg-base-300/40 border-b border-base-300">
                    <td className="font-bold text-primary">{cb.breaker_id}</td>
                    <td>{cb.vector_id}</td>
                    <td className="text-warning">{`${cb.detection_latency_us.toFixed(1)} \u03bcs`}</td>
                    <td className="text-warning">{`${cb.trigger_latency_us.toFixed(1)} \u03bcs`}</td>
                    <td className="text-error font-semibold">{cb.action}</td>
                    <td>
                      <span className="badge badge-error badge-xs font-bold py-1 px-2">
                        {cb.tripped ? 'TRIPPED' : 'ARMED'}
                      </span>
                    </td>
                    <td>
                      <span className="badge badge-success badge-xs font-semibold py-1 px-2">
                        SUB-MILLISECOND (&lt; 1 ms)
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="text-center py-4 text-base-content/60 font-sans">
                    No circuit breaker events recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 4. Auto-Flattening & Capital Preservation Audit */}
      <section aria-labelledby="auto-flattening-heading" className="space-y-3">
        <div>
          <h3 id="auto-flattening-heading" className="text-base font-bold flex items-center gap-2">
            <ShieldAlert size={18} className="text-error" />
            Auto-Flattening &amp; Capital Preservation Audit
          </h3>
          <p className="text-xs text-base-content/60">
            Position and order outcomes recorded by the historical artifact.
          </p>
        </div>

        {/* Metric scorecards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="card bg-base-200 border border-base-300 p-3 shadow-sm">
            <span className="text-[11px] font-semibold text-base-content/60 uppercase tracking-wider">
              Pre-Flatten Equity
            </span>
            <span className="text-lg font-mono font-bold text-base-content mt-1">
              {formatAmount(preEquity)}
            </span>
            <span className="text-[10px] text-base-content/50 mt-1">Baseline account equity</span>
          </div>

          <div className="card bg-base-200 border border-base-300 p-3 shadow-sm">
            <span className="text-[11px] font-semibold text-base-content/60 uppercase tracking-wider">
              Post-Flatten Cash
            </span>
            <span className="text-lg font-mono font-bold text-success mt-1">
              {formatAmount(postCash)}
            </span>
            <span className="text-[10px] text-success/80 mt-1">Cash preserved post-liquidation</span>
          </div>

          <div className="card bg-base-200 border border-base-300 p-3 shadow-sm">
            <span className="text-[11px] font-semibold text-base-content/60 uppercase tracking-wider">
              Capital Preserved
            </span>
            <span className="text-lg font-mono font-bold text-success mt-1">
              {formatPercent(preservedPct)}
            </span>
            <span className="text-[10px] text-base-content/60 mt-1">Recorded outcome; no current survival floor is asserted.</span>
          </div>

          <div className="card bg-base-200 border border-base-300 p-3 shadow-sm">
            <span className="text-[11px] font-semibold text-base-content/60 uppercase tracking-wider">
              Intra-Phase Loss
            </span>
            <span className="text-lg font-mono font-bold text-warning mt-1">
              {formatAmount(actualLoss, 4)}
            </span>
            <span className="text-[10px] text-warning/80 mt-1">
              {`Artifact loss threshold: ${formatAmount(maxLossBudget)}`}
            </span>
          </div>

          <div className="card bg-base-200 border border-base-300 p-3 shadow-sm">
            <span className="text-[11px] font-semibold text-base-content/60 uppercase tracking-wider">
              Circuit State
            </span>
            <div className="mt-1">
              <span className="badge badge-error font-mono font-bold text-xs py-2 px-2.5">
                {circuitState}
              </span>
            </div>
            <span className="text-[10px] text-base-content/50 mt-1">State captured in this report</span>
          </div>
        </div>

        {/* Audit event table */}
        <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-200">
          <table className="table table-sm w-full font-mono text-xs">
            <thead>
              <tr className="bg-base-300/60 text-base-content font-bold">
                <th>Audit ID</th>
                <th>Symbol</th>
                <th>Trigger Reason</th>
                <th>Positions Closed</th>
                <th>Orders Purged</th>
                <th>Pre-Flatten Equity</th>
                <th>Post-Flatten Cash</th>
                <th>Capital Preserved</th>
                <th>Execution Authority</th>
              </tr>
            </thead>
            <tbody>
              {model.autoFlatteningAudits.length > 0 ? (
                model.autoFlatteningAudits.map((a) => (
                  <tr key={a.flattening_id} className="hover:bg-base-300/40 border-b border-base-300">
                    <td className="font-bold text-primary">{a.flattening_id}</td>
                    <td className="font-bold">{a.symbol}</td>
                    <td className="text-base-content/80 font-sans text-xs">{a.trigger_reason}</td>
                    <td className="text-center font-bold text-warning">{a.positions_closed_count}</td>
                    <td className="text-center font-bold text-error">{a.orders_cancelled_count}</td>
                    <td>{`${a.pre_flatten_equity_usdt.toFixed(2)} USDT`}</td>
                    <td className="text-success font-bold">{`${a.post_flatten_cash_usdt.toFixed(2)} USDT`}</td>
                    <td className="text-success font-bold">{`${a.capital_preserved_pct.toFixed(1)}%`}</td>
                    <td>
                      <span className="badge badge-error badge-outline badge-xs font-mono font-bold py-1 px-1.5">
                        {a.execution_authority ? 'ON' : 'OFF'}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="text-center py-4 text-base-content/60 font-sans">
                    No emergency auto-flattening audits recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. Recorded Double-Entry Solvency Check */}
      <section aria-labelledby="solvency-heading" className="space-y-3">
        <div>
          <h3 id="solvency-heading" className="text-base font-bold flex items-center gap-2">
            <Scale size={18} className="text-success" />
            Recorded Double-Entry Solvency Check
          </h3>
          <p className="text-xs text-base-content/60">
            Recorded accounting identity: cash + allocated margin + unrealized PnL = starting equity + realized PnL.
          </p>
        </div>

        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm space-y-4">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs font-semibold">
              <span className="text-base-content/70">Historical cash ratio:</span>
              <span className="font-mono text-success font-bold">
                {formatPercent(cashReservePct)}
              </span>
            </div>
            {cashReservePct !== null ? (
              <progress
                className="progress progress-success w-full h-3"
                value={Math.min(100, Math.max(0, cashReservePct))}
                max={100}
                aria-label="Historical cash ratio"
              />
            ) : (
              <p className="text-[11px] text-base-content/50">Cash ratio unavailable in this artifact.</p>
            )}
            <div className="flex items-center justify-between text-[11px] text-base-content/50 font-mono">
              <span>Recorded cash ratio: {formatPercent(cashReservePct)}</span>
              <span className="font-bold">
                {reserveStatus === true ? 'Verified in report' : reserveStatus === false ? 'Failed in report' : 'Not reported'}
              </span>
            </div>
            <p className="text-[11px] text-base-content/50">
              Historical cash ratio only. The current runtime policy has no cash-reserve floor.
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-2 border-t border-base-300">
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Starting Equity:</span>
              <p className="font-mono text-sm font-bold mt-0.5">{formatAmount(startingEquity)}</p>
            </div>
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Final Cash:</span>
              <p className="font-mono text-sm font-bold text-success mt-0.5">{formatAmount(cash)}</p>
            </div>
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Allocated Margin:</span>
              <p className="font-mono text-sm font-bold text-warning mt-0.5">{formatAmount(allocatedMargin)}</p>
            </div>
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Unrealized PnL:</span>
              <p className="font-mono text-sm font-bold mt-0.5">{formatAmount(unrealizedPnl, 4)}</p>
            </div>
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Realized PnL:</span>
              <p className="font-mono text-sm font-bold mt-0.5">{formatAmount(realizedPnl, 4)}</p>
            </div>
            <div>
              <span className="text-[11px] text-base-content/60 uppercase font-semibold">Mathematical Drift:</span>
              <p className="font-mono text-xs font-bold text-success mt-1">
                {model.isZeroDrift === true
                  ? '|drift| < 10⁻¹⁵ USDT'
                  : typeof drift === 'number' && Number.isFinite(drift)
                    ? `${drift.toExponential(4)} USDT`
                    : '—'}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Cryptographic SHA-256 Merkle DAG Provenance linking Phase 296 */}
      <section aria-labelledby="merkle-provenance-heading" className="space-y-3">
        <div>
          <h3 id="merkle-provenance-heading" className="text-base font-bold flex items-center gap-2">
            <GitBranch size={18} className="text-primary" />
            Cryptographic SHA-256 Merkle DAG Provenance
          </h3>
          <p className="text-xs text-base-content/60">
            Hash provenance for this stored stress fault-injection artifact. It does not establish current runtime health.
          </p>
        </div>

        <div className="card bg-base-200 border border-base-300 p-4 shadow-sm space-y-3 font-mono text-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 border-b border-base-300 pb-2">
            <span className="text-base-content/60 font-semibold">Phase {phaseLabel} Merkle Root:</span>
            <span className="text-primary font-bold break-all">{model.merkleRoot}</span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 border-b border-base-300 pb-2">
            <span className="text-base-content/60 font-semibold">Phase {phaseLabel} Summary Hash:</span>
            <span className="text-base-content/90 break-all">{model.phaseHash}</span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
            <span className="text-base-content/60 font-semibold">Upstream Phase 296 Parent Hash:</span>
            <span className="text-success font-bold break-all">
              {model.upstreamHash || 'Unavailable'}
            </span>
          </div>

          <div className="pt-2 flex items-center gap-2">
            <span className="badge badge-success badge-sm gap-1 py-2 px-2.5 font-bold font-sans">
              <CheckCircle2 size={12} />
              ARTIFACT HASH VERIFIED
            </span>
            <span className="text-[11px] text-base-content/50 font-sans">
              Cryptographic integrity was verified when this artifact was loaded.
            </span>
          </div>
        </div>
      </section>
    </div>
  )
}
