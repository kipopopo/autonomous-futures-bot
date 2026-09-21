export type DashboardPage =
  | 'overview'
  | 'creator'
  | 'learner'
  | 'microstructure'
  | 'risk'
  | 'accounting'
  | 'market'
  | 'execution'
  | 'strategy-activation'
  | 'lifecycle'
  | 'stress'

export function pageFromHash(hash: string): DashboardPage {
  const normalized = hash.replace(/^#\/?/, '')
  if (normalized === 'creator') return 'creator'
  if (normalized === 'learner') return 'learner'
  if (normalized === 'microstructure') return 'microstructure'
  if (normalized === 'risk') return 'risk'
  if (normalized === 'accounting') return 'accounting'
  if (normalized === 'market' || normalized === 'live-market') return 'market'
  if (normalized === 'execution' || normalized === 'paper-execution') return 'execution'
  if (normalized === 'strategy-activation' || normalized === 'activation') return 'strategy-activation'
  if (normalized === 'lifecycle' || normalized === 'mission-control') return 'lifecycle'
  if (normalized === 'stress' || normalized === 'stress-resilience' || normalized === 'resilience') return 'stress'
  return 'overview'
}
