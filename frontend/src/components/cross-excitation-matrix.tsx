/**
 * Hawkes Cross-Excitation Matrix Heatmap (Phase 293).
 *
 * Visualizes the 3x3 Hawkes branching matrix Gamma = [alpha_ij / beta_ij] across
 * staged candidates (BTCUSDT, ETHUSDT, SOLUSDT), highlighting self-excitation
 * and cross-asset jump spillovers (primary BTC/ETH -> satellite SOL).
 */

import { useMemo } from 'react'
import { ArrowRight, Layers } from 'lucide-react'

import { formatDecimals } from '@/lib/chart-utils'

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

export interface CrossExcitationMatrixProps {
  branchingMatrix?: Record<string, Record<string, string>>
  spectralRadius?: string | number
}

const DEFAULT_MATRIX: Record<string, Record<string, string>> = {
  BTCUSDT: { BTCUSDT: '0.2500', ETHUSDT: '0.1200', SOLUSDT: '0.0500' },
  ETHUSDT: { BTCUSDT: '0.1000', ETHUSDT: '0.2800', SOLUSDT: '0.0500' },
  SOLUSDT: { BTCUSDT: '0.1800', ETHUSDT: '0.1500', SOLUSDT: '0.3500' },
}

export function CrossExcitationMatrix({
  branchingMatrix,
  spectralRadius,
}: CrossExcitationMatrixProps) {
  const matrix = branchingMatrix || DEFAULT_MATRIX

  const rhoDisplay = useMemo(() => {
    if (spectralRadius !== undefined && spectralRadius !== null) {
      const num = Number(spectralRadius)
      return Number.isFinite(num) ? formatDecimals(num, 4) : String(spectralRadius)
    }
    return '0.4286'
  }, [spectralRadius])

  function getIntensityColor(valStr: string, isDiagonal: boolean) {
    const v = parseFloat(valStr) || 0.0
    if (v >= 0.3) {
      return isDiagonal
        ? 'bg-error/20 border-error/40 text-error'
        : 'bg-error/30 border-error/60 text-error font-bold'
    }
    if (v >= 0.15) {
      return isDiagonal
        ? 'bg-warning/20 border-warning/40 text-warning'
        : 'bg-warning/25 border-warning/50 text-warning'
    }
    if (v >= 0.08) {
      return 'bg-info/15 border-info/30 text-info'
    }
    return 'bg-base-300/40 border-base-300 text-base-content/70'
  }

  return (
    <div className="card bg-base-200 border border-base-300 shadow-md p-4 w-full">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3 border-b border-base-300 pb-2">
        <div className="flex items-center gap-2">
          <Layers size={17} className="text-secondary" />
          <h3 className="font-semibold text-sm">Hawkes Cross-Excitation Matrix (Γ)</h3>
        </div>
        <div className="text-xs font-mono text-base-content/70">
          Branching Spectral Radius: <strong className="text-primary font-bold">ρ = {rhoDisplay}</strong>
        </div>
      </div>

      <p className="text-xs text-base-content/70 mb-3">
        Rows: <em>Affected Asset</em> (receiver) · Columns: <em>Trigger Asset</em> (initiator).
        Off-diagonals quantify cross-market jump spillover intensity.
      </p>

      <div className="overflow-x-auto">
        <table className="table table-xs w-full text-center border-collapse">
          <thead>
            <tr>
              <th className="bg-base-300/50 text-left font-mono text-[11px] py-2">Affected \ Trigger</th>
              {SYMBOLS.map((sym) => (
                <th key={sym} className="bg-base-300/50 font-mono text-[11px] py-2">
                  {sym.replace('USDT', '')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SYMBOLS.map((rowSym) => (
              <tr key={rowSym} className="hover:bg-base-300/20">
                <td className="font-mono font-bold text-left text-[11px] py-2 border-r border-base-300/50">
                  {rowSym.replace('USDT', '')}
                </td>
                {SYMBOLS.map((colSym) => {
                  const isDiag = rowSym === colSym
                  const val = matrix[rowSym]?.[colSym] ?? (isDiag ? '0.2500' : '0.1000')
                  const colorClass = getIntensityColor(val, isDiag)

                  return (
                    <td key={colSym} className="p-1">
                      <div
                        className={`rounded border py-2 px-1 font-mono text-xs ${colorClass}`}
                        title={`${rowSym} response to ${colSym} arrival: ${val}`}
                      >
                        <div className="font-bold">{val}</div>
                        <div className="text-[9px] opacity-70">
                          {isDiag ? 'Self' : `${colSym.slice(0, 3)}→${rowSym.slice(0, 3)}`}
                        </div>
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between text-[11px] font-mono text-base-content/60 mt-3 pt-2 border-t border-base-300/50">
        <span className="flex items-center gap-1 text-info">
          <ArrowRight size={12} /> Spillover contagion: BTC/ETH → SOL
        </span>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded bg-info/20 border border-info/30" /> &lt;0.15
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded bg-warning/25 border border-warning/50" /> 0.15-0.30
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded bg-error/30 border border-error/60" /> &gt;0.30
          </span>
        </div>
      </div>
    </div>
  )
}
