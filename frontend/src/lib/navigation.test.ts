import { describe, expect, it } from 'vitest'

import { pageFromHash } from './navigation'

describe('pageFromHash', () => {
  it('routes the supported creator hash', () => {
    expect(pageFromHash('#/creator')).toBe('creator')
    expect(pageFromHash('#creator')).toBe('creator')
  })

  it('falls back to Overview for unsupported or empty hashes', () => {
    expect(pageFromHash('')).toBe('overview')
    expect(pageFromHash('#/signals')).toBe('overview')
    expect(pageFromHash('#')).toBe('overview')
  })
})
