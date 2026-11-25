import { useQuery } from '@tanstack/react-query'

export interface Health {
  version: string
  mode: string
  started_at: string
  uptime_seconds: number
  database: 'connected' | 'unavailable'
  source_status: 'ready' | 'incomplete' | 'uninitialized' | 'unavailable' | 'error'
  last_ingestion_at: string | null
  last_evaluation_at: string | null
  missing_inputs: number | null
  warnings: string[]
}

export interface Counts {
  events: number
  contracts: number
  forecasts: number
  resolved_events: number
  evaluated_forecasts: number
  missing_forecasts: number
  invalid_forecasts: number
  unresolved_forecasts: number
}

export interface Portfolio {
  currency: 'USD'
  starting_cash: string
  current_cash: string
  open_positions: number
  realized_pnl: string
  transactions: number
  return_pct: number | null
  win_rate: number | null
}

export interface Activity {
  kind: string
  at: string
  description: string
}
export interface Overview {
  counts: Counts
  mean_brier: number | null
  portfolio: Portfolio | null
  activity: Activity[]
}
export interface Model {
  id: string
  version: string
  description: string
  status: string
}
export interface Forecast {
  id: string
  model_id: string
  model_version: string
  probability: number
  generated_at: string
  cutoff_at: string
  observation_ids: string[]
  quality: string
}
export interface Resolution {
  outcome: boolean
  resolved_at: string
  available_at: string
  provenance: string
}
export interface Contract {
  id: string
  label: string
  lower: number | null
  upper: number | null
  forecast: Forecast | null
  resolution: Resolution | null
  issue: string | null
}
export interface ResearchEvent {
  id: string
  title: string
  category: string
  description: string
  opens_at: string
  closes_at: string
  state: 'resolved' | 'unresolved'
  contracts: Contract[]
}
export interface Observation {
  id: string
  source: string
  issued_at: string | null
  available_at: string | null
  ingested_at: string
  provenance: string
  counts: Record<string, number>
  total: number
}
export interface EventDetail extends ResearchEvent {
  observations: Observation[]
}
export interface Evaluation {
  id: string
  event_id: string
  event_title: string
  contract_id: string
  contract_label: string
  forecast_id: string
  model_id: string
  model_version: string
  resolution_id: string
  probability: number
  outcome: boolean
  metric: string
  score: number
  evaluated_at: string
  context: string
}
export interface Evaluations {
  counts: Counts
  mean_brier: number | null
  records: Evaluation[]
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

export function useResource<T>(path: string, enabled = true) {
  return useQuery<T, Error>({
    queryKey: ['api', path],
    queryFn: async ({ signal }) => {
      const response = await fetch('/api/v1' + path, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(8000)]),
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => null)
        if (path === '/health' && response.status === 503 && detail?.database === 'unavailable') {
          return detail as T
        }
        throw new ApiError(
          response.status,
          typeof detail?.detail === 'string'
            ? detail.detail
            : 'The request returned HTTP ' + response.status + '.',
        )
      }
      return (await response.json()) as T
    },
    retry: false,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    networkMode: 'always',
    staleTime: 0,
    enabled,
  })
}

const utcDate = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const utcTime = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})
export function stamp(value: string | null) {
  if (value === null) return 'Unavailable'
  const date = new Date(value)
  return utcDate.format(date) + ' · ' + utcTime.format(date) + ' UTC'
}
export function clockTime(value: number) {
  return utcTime.format(value)
}
export function uptime(seconds: number) {
  const n = Math.floor(seconds)
  if (n < 60) return n + 's'
  if (n < 3600) return Math.floor(n / 60) + 'm ' + (n % 60) + 's'
  return Math.floor(n / 3600) + 'h ' + Math.floor((n % 3600) / 60) + 'm'
}
export function money(value: string) {
  // The API serializes exact decimal strings. Keep the display exact for large balances.
  const [integer, fraction = ''] = value.split('.')
  const negative = integer.startsWith('-')
  const grouped = integer.replace('-', '').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (negative ? '−$' : '$') + grouped + '.' + fraction.padEnd(2, '0')
}
export function percent(probability: number) {
  return new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 2 }).format(
    probability,
  )
}
export function display(value: string) {
  return value.replace(/[_-]/g, ' ')
}
export function counted(value: number, singular: string) {
  return value + ' ' + singular + (value === 1 ? '' : 's')
}
