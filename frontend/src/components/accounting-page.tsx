import { CheckCircle2, History, Layers, Scale } from 'lucide-react'

import type { AccountingModel } from '@/lib/canary'

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

export function AccountingPage({ model }: { model: AccountingModel }) {
  return (
    <section className="panel" aria-labelledby="accounting-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Accounting Plane / Double-Entry Ledger</p>
          <h2 id="accounting-heading">Mathematical Zero-Drift Balance Reconciliation</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`status-chip ${model.isZeroDrift ? 'status-verified' : 'status-error'}`}>
            <CheckCircle2 size={14} />
            {model.isZeroDrift ? 'ZERO-DRIFT VERIFIED (|drift| < 10\u207b\u00b9\u2075)' : 'DRIFT ANOMALY DETECTED'}
          </span>
        </div>
      </div>

      <p className="page-subtitle mb-4">
        Strict double-entry accounting reconciliation guaranteeing mathematical equality between equity snapshots and
        transactional fill ledgers across all staged tracks. Zero-drift tolerance strictly bounds numerical imprecision.
      </p>

      {/* Identity Card */}
      <div className="identity-card mb-6" style={{ padding: '1.25rem' }}>
        <div className="section-heading mb-3">
          <div className="flex items-center gap-2">
            <Scale className="text-primary" size={20} />
            <div>
              <p className="eyebrow">Double-Entry Conservation Formula</p>
              <h3 className="text-sm font-semibold font-mono">
                Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL
              </h3>
            </div>
          </div>
          <span className="status-chip status-verified">
            \u0394 = {model.drift} USDT
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-2">
          <div>
            <span className="field-label">Starting Capital</span>
            <p className="font-mono text-base font-semibold">{model.startingCapital} USDT</p>
          </div>
          <div>
            <span className="field-label">Final Cash</span>
            <p className="font-mono text-base font-semibold text-primary">{model.finalCash} USDT</p>
          </div>
          <div>
            <span className="field-label">Realized PnL</span>
            <p className="font-mono text-base font-semibold text-warning">{model.realizedPnl} USDT</p>
          </div>
          <div>
            <span className="field-label">Total Fees & Slippage</span>
            <p className="font-mono text-base font-semibold">{model.totalFees} USDT</p>
          </div>
        </div>
      </div>

      {/* Multi-Track Simulation Ledger */}
      <div className="inventory-panel mb-6">
        <div className="section-heading">
          <div>
            <p className="eyebrow flex items-center gap-1.5"><Layers size={14} /> Multi-Track Ledger</p>
            <h3>Simulation Track Reconciliation Results</h3>
          </div>
          <span className="section-meta">{model.tracks.length} tracks verified</span>
        </div>

        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead>
              <tr>
                <th>Track ID</th>
                <th>Track Name</th>
                <th>Starting Equity</th>
                <th>Final Cash</th>
                <th>Realized PnL</th>
                <th>Fees Paid</th>
                <th>Orders (Placed/Filled/Rej)</th>
                <th>Balance Drift</th>
                <th>Reconciliation</th>
              </tr>
            </thead>
            <tbody>
              {model.tracks.map((track) => (
                <tr key={track.track_id}>
                  <td><code>{track.track_id}</code></td>
                  <td><strong>{track.track_name.split('(')[0].trim()}</strong></td>
                  <td className="font-mono">{track.starting_equity_usdt}</td>
                  <td className="font-mono">{track.final_cash_usdt}</td>
                  <td className="font-mono text-warning">{track.realized_pnl_usdt}</td>
                  <td className="font-mono">{track.total_fees_usdt}</td>
                  <td className="font-mono">{track.orders_placed_count} / {track.orders_filled_count} / {track.orders_rejected_count}</td>
                  <td className="font-mono text-primary">{track.drift_usdt}</td>
                  <td>
                    <span className={`status-chip ${track.zero_balance_drift ? 'status-verified' : 'status-error'}`}>
                      {track.zero_balance_drift ? 'ZERO DRIFT' : 'DRIFT'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Balance Snapshots Stream */}
      <div className="inventory-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow flex items-center gap-1.5"><History size={14} /> Snapshot History</p>
            <h3>Granular Balance Snapshots</h3>
          </div>
          <span className="section-meta">{model.snapshots.length} snapshots recorded</span>
        </div>

        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead>
              <tr>
                <th>Timestamp (MYT)</th>
                <th>Track</th>
                <th>Trigger Event</th>
                <th>Cash (USDT)</th>
                <th>Allocated Margin</th>
                <th>Realized PnL</th>
                <th>Balance Drift</th>
              </tr>
            </thead>
            <tbody>
              {model.snapshots.map((snap) => (
                <tr key={snap.snapshot_id}>
                  <td className="font-mono text-xs">{formatMyt(snap.timestamp_utc)}</td>
                  <td><code>{snap.track_id}</code></td>
                  <td className="font-mono text-xs"><strong>{snap.trigger_event}</strong></td>
                  <td className="font-mono">{snap.cash_usdt}</td>
                  <td className="font-mono">{snap.allocated_margin_usdt}</td>
                  <td className="font-mono">{snap.realized_pnl_usdt}</td>
                  <td className="font-mono text-primary">{snap.drift_usdt}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
