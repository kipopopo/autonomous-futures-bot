import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchCreatorQualifications, fetchOverviewData } from './api'

function response(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('fetchCreatorQualifications', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls the verified read-only list route and returns its payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, {
      verified: true,
      candidate_count: 1,
      qualification_count: 1,
      missing_candidate_ids: [],
      qualifications: [],
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchCreatorQualifications()

    expect(result?.verified).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/creator/qualifications', {
      headers: { Accept: 'application/json' },
    })
  })

  it('maps missing evidence to null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(404)))

    await expect(fetchCreatorQualifications()).resolves.toBeNull()
  })

  it('rejects integrity failures instead of returning an empty success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(503)))

    await expect(fetchCreatorQualifications()).rejects.toThrow(
      'GET /api/v1/creator/qualifications failed with HTTP 503',
    )
  })
})

describe('fetchOverviewData metric-quality qualification evidence', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('preserves a 503 from the dedicated read-only route as an integrity error', async () => {
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      if (path === '/api/v1/learner/metric-quality-qualification') return response(503)
      if (path === '/health') return response(200, {})
      if (path === '/api/v1/dataset/bundle') return response(200, {})
      if (path === '/api/v1/dataset/components') return response(200, {})
      return response(404)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchOverviewData()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/learner/metric-quality-qualification', {
      headers: { Accept: 'application/json' },
    })
    expect(result.learnerMetricQualityQualification).toBeNull()
    expect(result.learnerMetricQualityQualificationError).toBe(
      'GET /api/v1/learner/metric-quality-qualification failed with HTTP 503',
    )
  })
})
