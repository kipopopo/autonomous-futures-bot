import { Activity, AlertTriangle, CheckCircle2, Cpu, Gauge, Zap } from 'lucide-react'

import type { HawkesSnapshot, MicrostructureModel } from '@/lib/canary'

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

function regimeBadge(regime: string) {
  if (regime.includes('SUPERCRITICAL')) {
    return <span className="status-chip status-error"><AlertTriangle size={14} /> SUPERCRITICAL CASCADE</span>
  }
  if (regime.includes('SEVERE') || regime.includes('ELEVATED')) {
    return <span className="status-chip status-warning"><AlertTriangle size={14} /> SEVERE HAWKES CONTROLS</span>
  }
  return <span className="status-chip status-verified"><CheckCircle2 size={14} /> NOMINAL STABILITY</span>
}

export function MicrostructurePage({ model }: { model: MicrostructureModel }) {
  const isElevated = model.isHawkesElevated
  const isSupercritical = model.isSupercritical

  return (
    <section className="panel" aria-labelledby="microstructure-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Microstructure Plane / Telemetry Engine</p>
          <h2 id="microstructure-heading">Hawkes Process Jump Intensity & Order Cascades</h2>
        </div>
        <div className="flex items-center gap-2">
          {regimeBadge(model.currentRegime)}
        </div>
      </div>

      <p className="page-subtitle mb-4">
        Observational telemetry modeling multivariate mutually exciting jump arrival cascades across staged candidates
        (<code>BTCUSDT</code>, <code>ETHUSDT</code>, <code>SOLUSDT</code>). Real-time spectral radius detection triggers
        passive limit offset cushioning and pacing throttling.
      </p>

      {/* Primary Fact Grid */}
      <div className="fact-grid mb-6">
        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Gauge size={14} /> Max Spectral Radius</p>
          <p className="fact-value font-mono">{model.maxSpectralRadius.toFixed(6)}</p>
          <p className="fact-detail">
            {isSupercritical
              ? 'Runaway cascade boundary (\u03c1 \u2265 1.0) breached'
              : isElevated
                ? 'Elevated hazard cushion (\u03c1 \u2265 0.85) active'
                : 'Stable subcritical regime (\u03c1 < 0.85)'}
          </p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Zap size={14} /> Peak Jump Intensity</p>
          <p className="fact-value font-mono">{model.maxJumpIntensity.toFixed(4)} \u03bb/s</p>
          <p className="fact-detail">Dynamic order arrival rate (\u03bb\u1d62(t))</p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Cpu size={14} /> Staged Candidates</p>
          <p className="fact-value font-mono">{model.candidates.length}</p>
          <p className="fact-detail">{model.candidates.join(', ') || '\u2014'}</p>
        </article>

        <article className="fact-card">
          <p className="eyebrow flex items-center gap-1.5"><Activity size={14} /> Phase Telemetry</p>
          <p className="fact-value font-mono uppercase">{model.phase}</p>
          <p className="fact-detail">Cryptographic DAG verified</p>
        </article>
      </div>

      {/* Candidates Detail Table */}
      <div className="inventory-panel mb-6">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Candidate Registry Manifest v2</p>
            <h3>Candidate Microstructure States</h3>
          </div>
          <span className="section-meta">{Object.keys(model.latestBySymbol).length} symbols tracked</span>
        </div>

        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Jump Intensity (\u03bb)</th>
                <th>Branching Ratio</th>
                <th>Spectral Radius (\u03c1)</th>
                <th>Self-Excitation (\u03b1)</th>
                <th>Pacing Interval</th>
                <th>Limit Cushion</th>
                <th>Cascade State</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(model.latestBySymbol).map(([symbol, item]: [string, HawkesSnapshot]) => (
                <tr key={symbol}>
                  <td><strong>{symbol}</strong></td>
                  <td className="font-mono">{item.jump_intensity}</td>
                  <td className="font-mono">{item.branching_ratio}</td>
                  <td className="font-mono">{item.spectral_radius}</td>
                  <td className="font-mono">{item.self_excitation_alpha}</td>
                  <td className="font-mono">{item.pacing_interval_ms} ms</td>
                  <td className="font-mono">{item.limit_offset_cushion_bps} bps</td>
                  <td>
                    <span className={`status-chip ${item.regime.includes('SUPERCRITICAL') ? 'status-error' : item.regime.includes('SEVERE') ? 'status-warning' : 'status-verified'}`}>
                      {item.cascade_state}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Hawkes Snapshots Historical Telemetry */}
      <div className="inventory-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Event Log</p>
            <h3>Recent Hawkes Cascade Snapshots</h3>
          </div>
          <span className="section-meta">{model.snapshots.length} recorded events</span>
        </div>

        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead>
              <tr>
                <th>Time (MYT)</th>
                <th>Track ID</th>
                <th>Symbol</th>
                <th>Regime</th>
                <th>Spectral Radius</th>
                <th>Pacing</th>
                <th>Limit Offset Cushion</th>
              </tr>
            </thead>
            <tbody>
              {model.snapshots.map((snap) => (
                <tr key={snap.record_id}>
                  <td className="font-mono text-xs">{formatMyt(snap.timestamp_utc)}</td>
                  <td><code>{snap.track_id}</code></td>
                  <td><strong>{snap.symbol}</strong></td>
                  <td>{regimeBadge(snap.regime)}</td>
                  <td className="font-mono">{snap.spectral_radius}</td>
                  <td className="font-mono">{snap.pacing_interval_ms} ms</td>
                  <td className="font-mono">{snap.limit_offset_cushion_bps} bps</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
