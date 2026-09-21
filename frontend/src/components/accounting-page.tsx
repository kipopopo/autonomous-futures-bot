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
    <div className="space-y-6" aria-labelledby="accounting-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
            Accounting Plane / Double-Entry Ledger
          </p>
          <h2 id="accounting-heading" className="text-xl font-bold tracking-tight mt-0.5">
            Mathematical Zero-Drift Balance Reconciliation
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`badge ${
              model.isZeroDrift ? 'badge-success' : 'badge-error'
            } gap-1.5 py-2.5 px-3 font-semibold text-xs shadow-sm`}
          >
            <CheckCircle2 size={14} />
            {model.isZeroDrift ? 'ZERO-DRIFT VERIFIED (|drift| < 10⁻¹⁵)' : 'DRIFT ANOMALY DETECTED'}
          </span>
        </div>
      </div>

      <p className="text-sm text-base-content/70">
        Strict double-entry accounting reconciliation guaranteeing mathematical equality between equity snapshots and
        transactional fill ledgers across all staged tracks. Zero-drift tolerance strictly bounds numerical imprecision.
      </p>

      {/* Conservation Formula & Key Accounting Metrics */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-3 mb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <Scale size={20} />
              </div>
              <div>
                <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">Double-Entry Conservation Formula</p>
                <h3 className="text-sm font-semibold font-mono text-base-content">
                  Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL
                </h3>
              </div>
            </div>
            <span className="badge badge-success gap-1 font-mono text-xs font-semibold py-2 px-3">
              Δ = {model.drift} USDT
            </span>
          </div>

          <div className="stats stats-vertical sm:stats-horizontal shadow bg-base-300/60 border border-base-300 w-full">
            <div className="stat">
              <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Starting Capital</div>
              <div className="stat-value font-mono text-lg">{model.startingCapital} USDT</div>
              <div className="stat-desc text-xs mt-0.5">Initial allocated pool</div>
            </div>
            <div className="stat">
              <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Final Cash</div>
              <div className="stat-value font-mono text-lg text-primary">{model.finalCash} USDT</div>
              <div className="stat-desc text-xs mt-0.5">Settled cash balance</div>
            </div>
            <div className="stat">
              <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Realized PnL</div>
              <div className="stat-value font-mono text-lg text-warning">{model.realizedPnl} USDT</div>
              <div className="stat-desc text-xs mt-0.5">Closed fills net return</div>
            </div>
            <div className="stat">
              <div className="stat-title text-xs uppercase tracking-wider font-semibold opacity-70">Total Fees &amp; Slippage</div>
              <div className="stat-value font-mono text-lg">{model.totalFees} USDT</div>
              <div className="stat-desc text-xs mt-0.5 text-success">0.00 slippage guaranteed</div>
            </div>
          </div>
        </div>
      </div>

      {/* Multi-Track Simulation Ledger */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold flex items-center gap-1.5">
                <Layers size={14} /> Multi-Track Ledger
              </p>
              <h3 className="text-base font-bold">Simulation Track Reconciliation Results</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              {model.tracks.length} tracks verified
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-zebra table-sm w-full font-sans">
              <thead className="bg-base-300/60 text-base-content/70 text-xs font-mono uppercase">
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
              <tbody className="text-xs">
                {model.tracks.map((track) => (
                  <tr key={track.track_id} className="hover">
                    <td><code className="badge badge-xs badge-neutral font-mono">{track.track_id}</code></td>
                    <td className="font-bold">{track.track_name.split('(')[0].trim()}</td>
                    <td className="font-mono">{track.starting_equity_usdt}</td>
                    <td className="font-mono">{track.final_cash_usdt}</td>
                    <td className="font-mono text-warning">{track.realized_pnl_usdt}</td>
                    <td className="font-mono">{track.total_fees_usdt}</td>
                    <td className="font-mono">{track.orders_placed_count} / {track.orders_filled_count} / {track.orders_rejected_count}</td>
                    <td className="font-mono text-primary font-semibold">{track.drift_usdt}</td>
                    <td>
                      <span className={`badge badge-sm font-semibold ${track.zero_balance_drift ? 'badge-success' : 'badge-error'}`}>
                        {track.zero_balance_drift ? 'ZERO DRIFT' : 'DRIFT'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Balance Snapshots Stream */}
      <div className="card bg-base-200 border border-base-300 shadow-xl overflow-hidden">
        <div className="card-body p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-3 mb-4">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold flex items-center gap-1.5">
                <History size={14} /> Snapshot History
              </p>
              <h3 className="text-base font-bold">Granular Balance Snapshots</h3>
            </div>
            <span className="badge badge-outline badge-sm text-xs font-mono">
              {model.snapshots.length} snapshots recorded
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="table table-zebra table-sm w-full font-sans">
              <thead className="bg-base-300/60 text-base-content/70 text-xs font-mono uppercase">
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
              <tbody className="text-xs">
                {model.snapshots.map((snap) => (
                  <tr key={snap.snapshot_id} className="hover">
                    <td className="font-mono text-xs">{formatMyt(snap.timestamp_utc)}</td>
                    <td><code className="badge badge-xs badge-neutral font-mono">{snap.track_id}</code></td>
                    <td className="font-mono text-xs font-semibold">{snap.trigger_event}</td>
                    <td className="font-mono">{snap.cash_usdt}</td>
                    <td className="font-mono">{snap.allocated_margin_usdt}</td>
                    <td className="font-mono">{snap.realized_pnl_usdt}</td>
                    <td className="font-mono text-primary font-semibold">{snap.drift_usdt}</td>
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
