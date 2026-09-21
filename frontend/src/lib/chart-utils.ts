/**
 * Zero-dependency SVG Chart Utilities (Phase 293).
 *
 * Provides pure mathematical helpers for coordinate scaling, polyline paths,
 * gradient areas, and boundary calculations for the real-time Spectral Radius chart.
 */

/**
 * Compute the X coordinate for an SVG chart point based on index and width.
 */
export function computeX(
  index: number,
  totalPoints: number,
  width: number,
  padding = 32
): number {
  const chartWidth = Math.max(1, width - 2 * padding)
  if (totalPoints <= 1) {
    return padding + chartWidth / 2
  }
  const ratio = Math.max(0, Math.min(1, index / (totalPoints - 1)))
  return Number((padding + ratio * chartWidth).toFixed(2))
}

/**
 * Compute the Y coordinate for an SVG chart point (inverted SVG coordinates).
 */
export function computeY(
  value: number,
  minVal: number,
  maxVal: number,
  height: number,
  padding = 24
): number {
  const chartHeight = Math.max(1, height - 2 * padding)
  if (maxVal <= minVal) {
    return Number((padding + chartHeight / 2).toFixed(2))
  }
  const ratio = (value - minVal) / (maxVal - minVal)
  const clamped = Math.max(0, Math.min(1, ratio))
  // Invert because SVG y=0 is at the top
  const y = height - padding - clamped * chartHeight
  return Number(y.toFixed(2))
}

/**
 * Generate an SVG path `d` string (`M x0,y0 L x1,y1 ...`) for a series of values.
 */
export function generateSvgPath(
  points: number[],
  width: number,
  height: number,
  padding = 24,
  minVal = 0.0,
  maxVal = 1.2
): string {
  if (points.length === 0) return ''
  if (points.length === 1) {
    const x = computeX(0, 1, width, padding)
    const y = computeY(points[0], minVal, maxVal, height, padding)
    return `M ${x},${y} L ${x + 1},${y}`
  }

  const coords = points.map((val, idx) => {
    const x = computeX(idx, points.length, width, padding)
    const y = computeY(val, minVal, maxVal, height, padding)
    return `${x},${y}`
  })

  return `M ${coords.join(' L ')}`
}

/**
 * Generate a closed SVG area path `d` string for gradient fill beneath the line.
 */
export function generateAreaPath(
  points: number[],
  width: number,
  height: number,
  padding = 24,
  minVal = 0.0,
  maxVal = 1.2
): string {
  if (points.length === 0) return ''
  const linePath = generateSvgPath(points, width, height, padding, minVal, maxVal)
  const yBottom = (height - padding).toFixed(2)
  const xFirst = computeX(0, points.length, width, padding)
  const xLast = computeX(points.length - 1, points.length, width, padding)

  return `${linePath} L ${xLast},${yBottom} L ${xFirst},${yBottom} Z`
}

/**
 * Compute auto-scaling min and max bounds for dynamic range display,
 * ensuring thresholds (0.85 and 1.0) remain visible.
 */
export function computeBounds(
  points: number[],
  defaultMin = 0.0,
  defaultMax = 1.2
): { minVal: number; maxVal: number } {
  if (points.length === 0) {
    return { minVal: defaultMin, maxVal: defaultMax }
  }

  const minObserved = Math.min(...points)
  const maxObserved = Math.max(...points)

  // Enforce floor at 0.0 and minimum ceiling of 1.1 to show critical lines
  const minVal = Math.max(0.0, Math.min(defaultMin, minObserved * 0.9))
  const maxVal = Math.max(defaultMax, maxObserved * 1.15)

  return {
    minVal: Number(minVal.toFixed(4)),
    maxVal: Number(maxVal.toFixed(4)),
  }
}

/**
 * Format a floating-point number to fixed decimal string.
 */
export function formatDecimals(val: number, digits = 4): string {
  if (!Number.isFinite(val)) return '0.0000'
  return val.toFixed(digits)
}
