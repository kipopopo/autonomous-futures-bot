/**
 * Spectral Radius Real-Time Timeline SVG Line Chart (Phase 293).
 *
 * Zero external dependencies: pure SVG path rendering with dynamic auto-scaling,
 * linear gradient fill, live latest marker, and reference threshold lines for:
 * - rho = 0.85 (Critical Hazard Threshold)
 * - rho = 1.00 (Supercritical Runaway Boundary)
 */

import { useMemo } from 'react'
import { AlertTriangle, CheckCircle2, ShieldAlert } from 'lucide-react'

import {
  computeBounds,
  computeX,
  computeY,
  formatDecimals,
  generateAreaPath,
  generateSvgPath,
} from '@/lib/chart-utils'

export interface SpectralRadiusChartProps {
  history: number[]
  currentRho?: number
  isSupercritical?: boolean
  width?: number
  height?: number
}

export function SpectralRadiusChart({
  history,
  currentRho,
  isSupercritical = false,
  width = 720,
  height = 240,
}: SpectralRadiusChartProps) {
  const points = useMemo(() => {
    if (history.length === 0) {
      const defaultRho = currentRho ?? 0.428571
      return [defaultRho]
    }
    return history
  }, [history, currentRho])

  const latestVal = points[points.length - 1] ?? 0.428571

  const { minVal, maxVal } = useMemo(
    () => computeBounds(points, 0.0, 1.25),
    [points]
  )

  const padding = 36
  const linePath = useMemo(
    () => generateSvgPath(points, width, height, padding, minVal, maxVal),
    [points, width, height, padding, minVal, maxVal]
  )
  const areaPath = useMemo(
    () => generateAreaPath(points, width, height, padding, minVal, maxVal),
    [points, width, height, padding, minVal, maxVal]
  )

  const latestX = computeX(points.length - 1, points.length, width, padding)
  const latestY = computeY(latestVal, minVal, maxVal, height, padding)

  const y85 = computeY(0.85, minVal, maxVal, height, padding)
  const y100 = computeY(1.0, minVal, maxVal, height, padding)

  const strokeColor = latestVal >= 1.0 ? '#ef4444' : latestVal >= 0.85 ? '#f59e0b' : '#10b981'
  const gradientId = `spectral-grad-${latestVal >= 1.0 ? 'error' : latestVal >= 0.85 ? 'warning' : 'success'}`

  return (
    <div className="card bg-base-200 border border-base-300 shadow-md p-4 w-full">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <div className="font-semibold text-sm">Spectral Radius Timeline (ρ)</div>
          <span className="badge badge-neutral badge-xs py-2 px-2 font-mono">
            {points.length} ticks
          </span>
        </div>

        <div className="flex items-center gap-2">
          {latestVal >= 1.0 || isSupercritical ? (
            <span className="badge badge-error gap-1 py-2 px-2.5 font-bold font-mono text-xs animate-pulse">
              <AlertTriangle size={13} /> ρ = {formatDecimals(latestVal, 4)} (RUNAWAY)
            </span>
          ) : latestVal >= 0.85 ? (
            <span className="badge badge-warning gap-1 py-2 px-2.5 font-bold font-mono text-xs">
              <ShieldAlert size={13} /> ρ = {formatDecimals(latestVal, 4)} (HAZARD)
            </span>
          ) : (
            <span className="badge badge-success gap-1 py-2 px-2.5 font-bold font-mono text-xs">
              <CheckCircle2 size={13} /> ρ = {formatDecimals(latestVal, 4)} (STABLE)
            </span>
          )}
        </div>
      </div>

      <div className="relative w-full overflow-hidden">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto overflow-visible select-none"
          preserveAspectRatio="none"
          role="img"
          aria-label="Spectral radius timeline line chart"
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={strokeColor} stopOpacity="0.35" />
              <stop offset="100%" stopColor={strokeColor} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          <line
            x1={padding}
            y1={height - padding}
            x2={width - padding}
            y2={height - padding}
            stroke="currentColor"
            strokeOpacity="0.15"
            strokeWidth="1"
          />

          {/* Threshold 0.85 (Hazard) */}
          <line
            x1={padding}
            y1={y85}
            x2={width - padding}
            y2={y85}
            stroke="#f59e0b"
            strokeDasharray="4 4"
            strokeWidth="1.5"
            strokeOpacity="0.8"
          />
          <text
            x={width - padding + 4}
            y={y85 + 3}
            fill="#f59e0b"
            fontSize="10"
            fontFamily="monospace"
            textAnchor="start"
          >
            0.85 (Hazard)
          </text>

          {/* Threshold 1.00 (Supercritical) */}
          <line
            x1={padding}
            y1={y100}
            x2={width - padding}
            y2={y100}
            stroke="#ef4444"
            strokeDasharray="4 4"
            strokeWidth="1.5"
            strokeOpacity="0.85"
          />
          <text
            x={width - padding + 4}
            y={y100 + 3}
            fill="#ef4444"
            fontSize="10"
            fontFamily="monospace"
            textAnchor="start"
          >
            1.00 (Supercritical)
          </text>

          {/* Fill beneath path */}
          {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} />}

          {/* Line path */}
          {linePath && (
            <path
              d={linePath}
              fill="none"
              stroke={strokeColor}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Latest value dot */}
          <circle
            cx={latestX}
            cy={latestY}
            r="4"
            fill={strokeColor}
            stroke="white"
            strokeWidth="1.5"
          />
          <circle
            cx={latestX}
            cy={latestY}
            r="8"
            fill={strokeColor}
            fillOpacity="0.3"
            className="animate-ping"
          />
        </svg>
      </div>

      <div className="flex items-center justify-between text-[11px] font-mono text-base-content/60 mt-2 px-1">
        <span>History: -{points.length} ticks</span>
        <span>
          Range: [{formatDecimals(minVal, 2)} - {formatDecimals(maxVal, 2)}]
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block w-2.5 h-0.5 bg-amber-500" /> Hazard
          <span className="inline-block w-2.5 h-0.5 bg-red-500" /> Supercritical
        </span>
      </div>
    </div>
  )
}
