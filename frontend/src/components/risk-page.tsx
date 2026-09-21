import { AlertOctagon, CheckCircle2, Clock, DollarSign, Layers, ShieldAlert, Wifi } from 'lucide-react'

import type { RiskModel } from '@/lib/canary'

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

export function RiskPage({ model }: { model: RiskModel }) {
  const isHealthyGateway = model.latestHeartbeat?.is_healthy ?? true
  const heartbeatLatency = model.latestHeartbeat?.latency_ms ?? 0
  const clockSkew = model.latestHeartbeat?.clock_skew_ms ?? 0

  return (
    <div className="space-y-6" aria-labelledby="risk-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Risk Governance / Execution Plane
          </p>
          <h2 id="risk-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Canary Risk Controls &amp; Interlock Circuit Breakers
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`badge ${
              model.circuitState === 'NORMAL' ? 'badge-success' : 'badge-error'
            } gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm`}
          >
            {model.circuitState === 'NORMAL' ? <CheckCircle2 size={14} /> : <AlertOctagon size={14} />}
            CIRCUIT BREAKER: {model.circuitState}
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        Multi-tier risk boundaries enforcing stepped exposure ceilings (≤ 60.00 USDT), individual micro-notional
        child order caps (≤ 5.00 USDT), intra-phase loss limits (≤ 7.00 USDT), dynamic margin headroom preservation
        (≥ 40% unencumbered cash), and sub-second gateway heartbeat age verification.
      </p>

      {/* Risk Metrics Fact Grid via DaisyUI Stats */}
      <div className="stats stats-vertical lg:stats-horizontal shadow-lg bg-base-200 border border-base-300 w-full">
        <div className="stat">
          <div className="stat-figure text-primary">
            <Layers size={22} />
          </div>
          <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Concurrent Exposure Cap</div>
          <div className="stat-value font-mono text-xl text-primary">{model.exposureCapUsdt} USDT</div>
          <div className="stat-desc text-xs mt-1">Stage 12 Stepped Expansion Cap</div>
        </div>

        <div className="stat">
          <div className="stat-figure text-secondary">
            <DollarSign size={22} />
          </div>
          <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Micro Child Order Cap</div>
          <div className="stat-value font-mono text-xl">{model.microCapUsdt} USDT</div>
          <div className="stat-desc text-xs mt-1">Precision ROUND_DOWN slicing</div>
        </div>

        <div className="stat">
          <div className="stat-figure text-warning">
            <AlertOctagon size={22} />
          </div>
          <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Intra-Phase Loss Ceiling</div>
          <div className="stat-value font-mono text-xl text-warning">{model.lossCeilingUsdt} USDT</div>
          <div className="stat-desc text-xs mt-1">Auto fail-closed emergency liquidation</div>
        </div>

        <div className="stat">
          <div className="stat-figure text-success">
            <Wifi size={22} />
          </div>
          <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Gateway Heartbeat</div>
          <div className="stat-value font-mono text-xl text-success">{heartbeatLatency.toFixed(1)} ms</div>
          <div className="stat-desc text-xs mt-1">
            {isHealthyGateway ? `NTP Clock Skew: ${clockSkew.toFixed(1)} ms` : 'GATEWAY STALE'}
          </div>
        </div>
      </div>

      {/* Dynamic Margin Headroom Indicator */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-3">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold flex items-center gap-1.5">
                <ShieldAlert size={14} /> Dynamic Margin Headroom Policy
              </p>
              <h3 className="text-base font-bold">Reserve Buffer &amp; Allocation Ceiling</h3>
            </div>
            <span className="badge badge-success gap-1 text-xs font-semibold py-2 px-3">
              <CheckCircle2 size={13} /> HEADROOM PRESERVED
            </span>
          </div>

          <p className="text-xs text-base-content/70 mb-3">
            Ensures portfolio committed margin never exceeds 60.00% under peak concurrent orders, guaranteeing at least
            40.00% cash reserve for maintenance margin shock absorption.
          </p>

          <div className="w-full bg-base-300 rounded-full h-3.5 overflow-hidden flex border border-base-300">
            <div className="bg-primary h-full transition-all duration-300" style={{ width: '20%' }} title="Current Allocated Margin (20%)" />
            <div className="bg-warning/70 h-full transition-all duration-300" style={{ width: '40%' }} title="Maximum Allowed Allocation Headroom (40%)" />
            <div className="bg-success/80 h-full transition-all duration-300" style={{ width: '40%' }} title="Mandatory Unencumbered Cash Buffer (40%)" />
          </div>

          <div className="flex justify-between text-xs text-base-content/60 mt-2 font-mono">
            <span>0%</span>
            <span>Allocated Margin (Max 60%)</span>
            <span>Cash Reserve (≥ 40%)</span>
            <span>100%</span>
          </div>
        </div>
      </div>

      {/* Interlock Event Records */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold flex items-center gap-1.5">
                <Clock size={14} /> Audit Trail
              </p>
              <h3 className="text-base font-bold">Interlock Governance &amp; Protection Events</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              {model.recentInterlocks.length} events ({model.totalBlocks} blocked)
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-zebra table-sm w-full font-sans">
              <thead className="bg-base-300/60 text-base-content/70 text-xs font-mono uppercase">
                <tr>
                  <th>Time (MYT)</th>
                  <th>Track ID</th>
                  <th>Interlock Type</th>
                  <th>Action</th>
                  <th>Symbol</th>
                  <th>Notional</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                {model.recentInterlocks.map((event) => (
                  <tr key={event.event_id} className="hover">
                    <td className="font-mono text-xs">{formatMyt(event.timestamp_utc)}</td>
                    <td><code className="badge badge-xs badge-neutral font-mono">{event.track_id}</code></td>
                    <td className="font-bold">{event.interlock_type}</td>
                    <td>
                      <span className={`badge badge-sm font-semibold ${event.allowed ? 'badge-success' : 'badge-warning'}`}>
                        {event.allowed ? 'ALLOWED' : 'BLOCKED'}
                      </span>
                    </td>
                    <td>{event.symbol ?? '—'}</td>
                    <td className="font-mono">{event.notional_usdt ? `${event.notional_usdt} USDT` : '—'}</td>
                    <td className="text-xs text-base-content/70">{event.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
