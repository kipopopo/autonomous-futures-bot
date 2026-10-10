import { useMemo, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Filter,
  Receipt,
  Zap,
} from 'lucide-react'
import type { OrderFeedItem } from './types'
import { ProvenanceBadge } from './provenance-badge'

export interface OrderFeedTableProps {
  orders: OrderFeedItem[]
}

export function OrderFeedTable({ orders }: OrderFeedTableProps) {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('ALL')

  const filteredOrders = useMemo(() => {
    if (selectedSymbol === 'ALL') return orders
    return orders.filter((o) => o.symbol === selectedSymbol)
  }, [orders, selectedSymbol])

  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />

      {/* Title & Filter Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]">
            <Receipt className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Suapan Pesanan &amp; Log Pelaksanaan Langsung
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-emerald-500/10 border border-emerald-500/25 text-emerald-300">
                Maker 0.02%
              </span>
              <ProvenanceBadge source="LIVE EXCHANGE" />
            </div>
            <p className="text-xs text-zinc-400">
              Pelaksanaan pesanan pasaran had (maker limit) tanpa seretan yuran tinggi, direkodkan mengikut waktu Malaysia (MYT)
            </p>
          </div>
        </div>

        {/* Symbol Filter Controls */}
        <div className="flex items-center gap-1 bg-white/[0.03] p-1 rounded-xl border border-white/[0.08]">
          <Filter className="w-3.5 h-3.5 text-zinc-500 ml-2 mr-1" />
          {['ALL', 'SOLUSDT', 'ETHUSDT', 'BTCUSDT'].map((sym) => (
            <button
              key={sym}
              type="button"
              onClick={() => setSelectedSymbol(sym)}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-semibold transition-all ${
                selectedSymbol === sym
                  ? 'bg-gradient-to-r from-cyan-500/20 to-emerald-500/20 border border-cyan-500/30 text-white shadow-sm'
                  : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
              }`}
            >
              {sym === 'ALL' ? 'SEMUA' : sym.replace('USDT', '')}
            </button>
          ))}
        </div>
      </div>

      {/* Orders Table */}
      {filteredOrders.length === 0 ? (
        <div className="p-10 text-center text-xs text-zinc-500 font-mono">
          Tiada rekod pesanan bagi tapisan ini.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs text-left">
            <thead>
              <tr className="border-b border-white/[0.06] text-zinc-400 text-[11px] uppercase tracking-wider">
                <th className="pb-3 font-semibold">Waktu (MYT)</th>
                <th className="pb-3 font-semibold">Pasangan</th>
                <th className="pb-3 font-semibold">Tindakan / Jenis</th>
                <th className="pb-3 font-semibold text-right">Harga &amp; Kuantiti</th>
                <th className="pb-3 font-semibold text-right">Nilai Notional</th>
                <th className="pb-3 font-semibold text-right">Yuran Maker (0.02%)</th>
                <th className="pb-3 font-semibold text-right">PnL Direalisasi</th>
                <th className="pb-3 font-semibold text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {filteredOrders.map((ord) => {
                const isBuy = ord.side === 'BUY'
                const pnlPositive = ord.realizedPnlUsdt > 0
                const hasPnl = ord.realizedPnlUsdt !== 0

                return (
                  <tr
                    key={ord.orderId}
                    className="hover:bg-white/[0.02] transition-colors group"
                  >
                    {/* Timestamp in MYT */}
                    <td className="py-3 font-semibold text-zinc-300 whitespace-nowrap tabular-nums">
                      {ord.timestampMyt}
                    </td>

                    {/* Symbol */}
                    <td className="py-3">
                      <span className="font-bold text-white px-2 py-0.5 rounded-md bg-white/[0.05] border border-white/[0.08]">
                        {ord.symbol}
                      </span>
                    </td>

                    {/* Side & Type */}
                    <td className="py-3">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[11px] font-mono font-bold py-0.5 px-2 rounded-md border ${
                            isBuy
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                              : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                          }`}
                        >
                          {ord.side}
                        </span>
                        <span className="text-[11px] text-zinc-400">
                          {ord.orderType}
                        </span>
                      </div>
                    </td>

                    {/* Price & Quantity */}
                    <td className="py-3 text-right whitespace-nowrap">
                      <div className="font-bold text-white tabular-nums">
                        {`$${ord.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
                      </div>
                      <div className="text-[10px] text-zinc-400 tabular-nums">
                        {`${ord.quantity} unit`}
                      </div>
                    </td>

                    {/* Notional */}
                    <td className="py-3 text-right font-bold text-zinc-200 whitespace-nowrap tabular-nums">
                      {`$${ord.notionalUsdt.toFixed(2)} USDT`}
                    </td>

                    {/* Maker Fee */}
                    <td className="py-3 text-right whitespace-nowrap">
                      <span className="inline-flex items-center gap-1 text-amber-400 font-semibold tabular-nums">
                        <Zap className="w-3 h-3 text-amber-400 shrink-0" />
                        {`$${ord.makerFeeUsdt.toFixed(4)}`}
                      </span>
                    </td>

                    {/* Realized PnL */}
                    <td className="py-3 text-right whitespace-nowrap font-bold">
                      {hasPnl ? (
                        <span
                          className={`inline-flex items-center gap-0.5 tabular-nums ${
                            pnlPositive ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {pnlPositive ? (
                            <ArrowUpRight className="w-3.5 h-3.5" />
                          ) : (
                            <ArrowDownRight className="w-3.5 h-3.5" />
                          )}
                          {`${pnlPositive ? '+' : ''}$${ord.realizedPnlUsdt.toFixed(4)}`}
                        </span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>

                    {/* Status */}
                    <td className="py-3 text-center">
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono font-bold py-0.5 px-2 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        <CheckCircle2 className="w-2.5 h-2.5" />
                        {ord.status}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
