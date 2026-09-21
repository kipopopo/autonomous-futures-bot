export type DashboardPage =
  | 'overview'
  | 'creator'
  | 'learner'
  | 'microstructure'
  | 'risk'
  | 'accounting'
  | 'market'
  | 'execution'

export function pageFromHash(hash: string): DashboardPage {
  const normalized = hash.replace(/^#\/?/, '')
  if (normalized === 'creator') return 'creator'
  if (normalized === 'learner') return 'learner'
  if (normalized === 'microstructure') return 'microstructure'
  if (normalized === 'risk') return 'risk'
  if (normalized === 'accounting') return 'accounting'
  if (normalized === 'market' || normalized === 'live-market') return 'market'
  if (normalized === 'execution' || normalized === 'paper-execution') return 'execution'
  return 'overview'
}
