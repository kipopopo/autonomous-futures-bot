import type {
  BundleResponse,
  ComponentsResponse,
  CreatorRegistryResponse,
  DashboardApiData,
  HealthResponse,
} from './dashboard'

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

async function fetchOptionalCreatorRegistry(): Promise<CreatorRegistryResponse | null> {
  const path = '/api/v1/creator/registry'
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CreatorRegistryResponse
}

export async function fetchOverviewData(): Promise<DashboardApiData> {
  const [health, bundle, components, creatorRegistry] = await Promise.all([
    fetchJson<HealthResponse>('/health'),
    fetchJson<BundleResponse>('/api/v1/dataset/bundle'),
    fetchJson<ComponentsResponse>('/api/v1/dataset/components'),
    fetchOptionalCreatorRegistry(),
  ])

  return { health, bundle, components, creatorRegistry }
}
