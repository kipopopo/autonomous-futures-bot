import { describe, expect, it } from 'vitest'

import { pageFromHash } from './navigation'

describe('pageFromHash', () => {
  it('routes the supported pages', () => {
    expect(pageFromHash('#/creator')).toBe('creator')
    expect(pageFromHash('#creator')).toBe('creator')
    expect(pageFromHash('#/market')).toBe('market')
    expect(pageFromHash('#market')).toBe('market')
    expect(pageFromHash('#/learner')).toBe('learner')
    expect(pageFromHash('#learner')).toBe('learner')
    expect(pageFromHash('#/microstructure')).toBe('microstructure')
    expect(pageFromHash('#microstructure')).toBe('microstructure')
    expect(pageFromHash('#/risk')).toBe('risk')
    expect(pageFromHash('#risk')).toBe('risk')
    expect(pageFromHash('#/accounting')).toBe('accounting')
    expect(pageFromHash('#accounting')).toBe('accounting')
    expect(pageFromHash('#/execution')).toBe('execution')
    expect(pageFromHash('#execution')).toBe('execution')
    expect(pageFromHash('#/strategy-activation')).toBe('strategy-activation')
    expect(pageFromHash('#strategy-activation')).toBe('strategy-activation')
  })

  it('falls back to Overview for unsupported or empty hashes', () => {
    expect(pageFromHash('')).toBe('overview')
    expect(pageFromHash('#/unsupported')).toBe('overview')
    expect(pageFromHash('#')).toBe('overview')
  })
})
