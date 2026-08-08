import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchOverviewData } from './api'
import { buildOverviewModel } from './dashboard'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('buildOverviewModel', () => {
  it('builds verified operational facts from API responses', () => {
    const model = buildOverviewModel({
      health: {
        status: 'ok',
        service: 'autonomous-futures-data-api',
        paper_safe: true,
        execution_authority: false,
      },
      bundle: {
        verified: true,
        registry_hash: 'registry-hash',
        bundle_hash: 'bundle-hash',
        component_count: 2,
        bundle: {
          symbols: ['ETHUSDT', 'BTCUSDT'],
          primary_interval: '5m',
          context_interval: '15m',
          context_feature_policy: 'close_time_plus_1ms',
          time_start: '2026-08-07T00:00:00Z',
          time_end: '2026-08-07T01:00:00Z',
        },
      },
      components: {
        verified: true,
        component_count: 2,
        components: [
          {
            kind: 'kline',
            symbols: ['ETHUSDT'],
            interval: '5m',
            artifact_ref: 'ETHUSDT/manifest.json',
            data_ref: 'ETHUSDT/canonical.parquet',
            manifest_hash: 'manifest-eth',
            rows: 12,
            schema_version: 'dataset-manifest-v1',
          },
          {
            kind: 'kline',
            symbols: ['BTCUSDT'],
            interval: '5m',
            artifact_ref: 'BTCUSDT/manifest.json',
            data_ref: 'BTCUSDT/canonical.parquet',
            manifest_hash: 'manifest-btc',
            rows: 12,
            schema_version: 'dataset-manifest-v1',
          },
        ],
      },
    })

    expect(model.verification).toBe('verified')
    expect(model.paperSafe).toBe(true)
    expect(model.executionAuthority).toBe(false)
    expect(model.symbols).toEqual(['BTCUSDT', 'ETHUSDT'])
    expect(model.componentCount).toBe(2)
    expect(model.bundleHash).toBe('bundle-hash')
  })

  it('does not invent metrics when API data is unavailable', () => {
    const model = buildOverviewModel({ health: null, bundle: null, components: null })

    expect(model.verification).toBe('error')
    expect(model.componentCount).toBeNull()
    expect(model.bundleHash).toBeNull()
    expect(model.symbols).toEqual([])
  })

  it('fetches only the verified read-only Overview endpoints', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchOverviewData()

    expect(fetchMock).toHaveBeenCalledTimes(10)
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/health',
      '/api/v1/dataset/bundle',
      '/api/v1/dataset/components',
      '/api/v1/creator/registry',
      '/api/v1/creator/qualifications',
      '/api/v1/learner/artifact',
      '/api/v1/learner/run',
      '/api/v1/learner/training-evidence',
      '/api/v1/learner/quality-review',
      '/api/v1/learner/qualification',
    ])
  })

  it('rejects an unverified HTTP response instead of fabricating data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })))

    await expect(fetchOverviewData()).rejects.toThrow('503')
  })
})