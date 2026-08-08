import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchCreatorQualifications } from './api'

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
