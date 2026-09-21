import { describe, expect, it } from 'vitest'

import {
  computeBounds,
  computeX,
  computeY,
  formatDecimals,
  generateAreaPath,
  generateSvgPath,
} from './chart-utils'

describe('chart-utils', () => {
  describe('computeX', () => {
    it('centers single point when totalPoints is 1', () => {
      const x = computeX(0, 1, 100, 10)
      expect(x).toBe(50) // 10 + (100 - 20) / 2 = 50
    })

    it('computes correct evenly spaced X coordinates', () => {
      const width = 100
      const padding = 10
      // 3 points: index 0 -> 10, index 1 -> 50, index 2 -> 90
      expect(computeX(0, 3, width, padding)).toBe(10)
      expect(computeX(1, 3, width, padding)).toBe(50)
      expect(computeX(2, 3, width, padding)).toBe(90)
    })

    it('clamps ratio between 0 and 1', () => {
      expect(computeX(-1, 5, 100, 10)).toBe(10)
      expect(computeX(10, 5, 100, 10)).toBe(90)
    })
  })

  describe('computeY', () => {
    it('inverts coordinates for SVG coordinate system (higher value = lower Y)', () => {
      const height = 100
      const padding = 10
      const minVal = 0.0
      const maxVal = 1.0

      // Value 0.0 should be at the bottom: height - padding = 90
      expect(computeY(0.0, minVal, maxVal, height, padding)).toBe(90)

      // Value 1.0 should be at the top: padding = 10
      expect(computeY(1.0, minVal, maxVal, height, padding)).toBe(10)

      // Value 0.5 should be centered: 50
      expect(computeY(0.5, minVal, maxVal, height, padding)).toBe(50)
    })

    it('handles equal min and max gracefully', () => {
      const height = 100
      const padding = 10
      expect(computeY(0.5, 0.5, 0.5, height, padding)).toBe(50)
    })

    it('clamps values below min or above max', () => {
      const height = 100
      const padding = 10
      expect(computeY(-5.0, 0.0, 1.0, height, padding)).toBe(90)
      expect(computeY(5.0, 0.0, 1.0, height, padding)).toBe(10)
    })
  })

  describe('generateSvgPath', () => {
    it('returns empty string for empty points array', () => {
      expect(generateSvgPath([], 100, 100)).toBe('')
    })

    it('generates a short line for single point', () => {
      const path = generateSvgPath([0.5], 100, 100, 10, 0.0, 1.0)
      expect(path).toBe('M 50,50 L 51,50')
    })

    it('generates connected line segments for multiple points', () => {
      const path = generateSvgPath([0.0, 1.0], 100, 100, 10, 0.0, 1.0)
      expect(path).toBe('M 10,90 L 90,10')
    })
  })

  describe('generateAreaPath', () => {
    it('returns empty string for empty points', () => {
      expect(generateAreaPath([], 100, 100)).toBe('')
    })

    it('generates a closed polygon path down to bottom boundary', () => {
      const path = generateAreaPath([0.0, 1.0], 100, 100, 10, 0.0, 1.0)
      expect(path).toBe('M 10,90 L 90,10 L 90,90.00 L 10,90.00 Z')
    })
  })

  describe('computeBounds', () => {
    it('returns defaults for empty array', () => {
      const bounds = computeBounds([])
      expect(bounds.minVal).toBe(0.0)
      expect(bounds.maxVal).toBe(1.2)
    })

    it('expands upper bound to fit critical runaway threshold', () => {
      const bounds = computeBounds([0.4, 0.6, 0.8])
      expect(bounds.minVal).toBe(0.0)
      expect(bounds.maxVal).toBeGreaterThanOrEqual(1.2)
    })

    it('expands beyond default if values surge above 1.2', () => {
      const bounds = computeBounds([0.5, 1.5])
      expect(bounds.maxVal).toBeGreaterThanOrEqual(1.5 * 1.15)
    })
  })

  describe('formatDecimals', () => {
    it('formats number to fixed precision', () => {
      expect(formatDecimals(0.123456, 4)).toBe('0.1235')
      expect(formatDecimals(1.5, 2)).toBe('1.50')
    })

    it('handles non-finite values safely', () => {
      expect(formatDecimals(NaN)).toBe('0.0000')
      expect(formatDecimals(Infinity)).toBe('0.0000')
    })
  })
})
