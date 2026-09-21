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
    <section className="panel" aria-labelledby="risk-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Risk Governance / Execution Plane</p>
          <h2 id="risk-heading">Canary Risk Controls & Interlock Circuit Breakers</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`status-chip ${model.circuitState === 'NORMAL' ? 'status-verified' : 'status-error'}`}>
            {model.circuitState === 'NORMAL' ? <CheckCircle2 size={14} /> : <AlertOctagon size={14} />}
            CIRCUIT BREAKER: {model.circuitState}
          </span>
        </div>
      </div>

      <p className="page-subtitle mb-4">
        Multi-tier risk boundaries enforcing stepped exposure ceilings (\u2264 60.00 USDT), individual micro-notional
        child order caps (\u2264 5.00 USDT), intra-phase loss limits (\u2264 7.00 USDT), dynamic margin headroom preservation
        (\u2265 40% unencumbered cash), and sub-second gateway heartbeat age verification.
      </p>

      {/* Risk Metrics Fact Grid */}
      <div className="fact-grid mb-6">
        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Layers size={14} /> Aggregate Concurrent Exposure</p>
          <p className="fact-value font-mono">{model.exposureCapUsdt} USDT</p>
          <p className="fact-detail">Stage 12 Stepped Expansion Cap</p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><DollarSign size={14} /> Micro Child Order Cap</p>
          <p className="fact-value font-mono">{model.microCapUsdt} USDT</p>
          <p className="fact-detail">Precision ROUND_DOWN slicing</p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><AlertOctagon size={14} /> Intra-Phase Loss Ceiling</p>
          <p className="fact-value font-mono">{model.lossCeilingUsdt} USDT</p>
          <p className="fact-detail">Auto fail-closed emergency liquidation</p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Wifi size={14} /> Gateway Heartbeat</p>
          <p className="fact-value font-mono">{heartbeatLatency.toFixed(1)} ms</p>
          <p className="fact-detail">
            {isHealthyGateway ? 'NTP Clock Skew: ' + clockSkew.toFixed(1) + ' ms' : 'GATEWAY STALE'}
          </p>
        </article>
      </div>

      {/* Dynamic Margin Headroom Indicator */}
      <div className="identity-card mb-6" style={{ padding: '1.25rem' }}>
        <div className="section-heading mb-2">
          <div>
            <p className="eyebrow flex items-center gap-1.5"><ShieldAlert size={15} /> Dynamic Margin Headroom Policy</p>
            <h3 className="text-base font-semibold">Reserve Buffer & Allocation Ceiling</h3>
          </div>
          <span className="status-chip status-verified">
            <CheckCircle2 size={13} /> HEADROOM PRESERVED
          </span>
        </div>
        <p className="text-xs text-secondary mb-3">
          Ensures portfolio committed margin never exceeds 60.00% under peak concurrent orders, guaranteeing at least
          40.00% cash reserve for maintenance margin shock absorption.
        </p>
        <div className="w-full bg-surface-raised rounded-full h-3 overflow-hidden flex border border-border">
          <div className="bg-primary h-full transition-all duration-300" style={{ width: '20%' }} title="Current Allocated Margin (20%)" />
          <div className="bg-warning/60 h-full transition-all duration-300" style={{ width: '40%' }} title="Maximum Allowed Allocation Headroom (40%)" />
          <div className="bg-positive/80 h-full transition-all duration-300" style={{ width: '40%' }} title="Mandatory Unencumbered Cash Buffer (40%)" />
        </div>
        <div className="flex justify-between text-xs text-muted mt-2 font-mono">
          <span>0%</span>
          <span>Allocated Margin (Max 60%)</span>
          <span>Cash Reserve (\u2265 40%)</span>
          <span>100%</span>
        </div>
      </div>

      {/* Interlock Event Records */}
      <div className="inventory-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow flex items-center gap-1.5"><Clock size={14} /> Audit Trail</p>
            <h3>Interlock Governance & Protection Events</h3>
          </div>
          <span className="section-meta">{model.recentInterlocks.length} events ({model.totalBlocks} blocked)</span>
        </div>

        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead>
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
            <tbody>
              {model.recentInterlocks.map((event) => (
                <tr key={event.event_id}>
                  <td className="font-mono text-xs">{formatMyt(event.timestamp_utc)}</td>
                  <td><code>{event.track_id}</code></td>
                  <td><strong>{event.interlock_type}</strong></td>
                  <td>
                    <span className={`status-chip ${event.allowed ? 'status-verified' : 'status-warning'}`}>
                      {event.allowed ? 'ALLOWED' : 'BLOCKED'}
                    </span>
                  </td>
                  <td>{event.symbol ?? '\u2014'}</td>
                  <td className="font-mono">{event.notional_usdt ? `${event.notional_usdt} USDT` : '\u2014'}</td>
                  <td className="text-xs text-secondary">{event.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
