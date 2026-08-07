import type {
  BundleResponse,
  ComponentsResponse,
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

export async function fetchOverviewData(): Promise<DashboardApiData> {
  const [health, bundle, components] = await Promise.all([
    fetchJson<HealthResponse>('/health'),
    fetchJson<BundleResponse>('/api/v1/dataset/bundle'),
    fetchJson<ComponentsResponse>('/api/v1/dataset/components'),
  ])

  return { health, bundle, components }
}
