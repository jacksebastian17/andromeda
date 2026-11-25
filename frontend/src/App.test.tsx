import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { EventDetail, Health, Overview, Portfolio } from './data'

type Responses = Record<string, unknown>

function serve(responses: Responses) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input)
    const path = new URL(url, window.location.href).pathname
    if (!Object.hasOwn(responses, path)) {
      throw new Error(`Unexpected request: ${path}`)
    }
    const value = responses[path]
    return value instanceof Response ? value.clone() : Response.json(value)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const clients: QueryClient[] = []

const health: Health = {
  version: '9.8.7',
  mode: 'synthetic_research_paper_only',
  started_at: '2026-01-01T12:00:00Z',
  uptime_seconds: 123,
  database: 'connected',
  source_status: 'incomplete',
  last_ingestion_at: '2026-01-01T12:10:00Z',
  last_evaluation_at: '2026-01-01T12:10:01Z',
  missing_inputs: 1,
  warnings: ['Fixture observation missing'],
}

const portfolio: Portfolio = {
  currency: 'USD',
  starting_cash: '9007199254740993.01',
  current_cash: '9007199254740993.01',
  open_positions: 0,
  realized_pnl: '0.00',
  transactions: 0,
  return_pct: null,
  win_rate: null,
}

const overview: Overview = {
  counts: {
    events: 17,
    contracts: 39,
    forecasts: 26,
    resolved_events: 13,
    evaluated_forecasts: 20,
    missing_forecasts: 13,
    invalid_forecasts: 0,
    unresolved_forecasts: 6,
  },
  mean_brier: 0.1234,
  portfolio,
  activity: [
    { kind: 'ingestion', at: '2026-01-01T12:10:00Z', description: 'Ingested the audit dataset' },
  ],
}

const incomplete: EventDetail = {
  id: 'missing-source',
  title: 'A missing observation',
  category: 'binary',
  description: 'Checks source absence',
  state: 'unresolved',
  opens_at: '2026-01-01T12:00:00Z',
  closes_at: '2026-01-01T20:00:00Z',
  contracts: [
    {
      id: 'missing-binary',
      label: 'Relay status',
      lower: null,
      upper: null,
      forecast: null,
      resolution: null,
      issue: 'Source was unavailable',
    },
  ],
  observations: [],
}

function mount(path: string) {
  window.history.replaceState({}, '', path)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
  return client
}

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear())
})

describe('research terminal', () => {
  it('identifies its operating mode while the first response is pending', () => {
    vi.stubGlobal('fetch', () => new Promise<Response>(() => {}))
    mount('/')
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeVisible()
    expect(screen.getByText(/loading workspace data/i)).toBeVisible()
    const sidebar = within(screen.getByRole('complementary'))
    expect(sidebar.getByText('Synthetic research')).toBeVisible()
    expect(sidebar.getByText('Paper only')).toBeVisible()
  })

  it('reports backend failure on a direct page load', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network error')))
    mount('/markets')
    expect(await screen.findByText(/data unavailable/i)).toBeVisible()
    expect(screen.queryByText(/no events available/i)).not.toBeInTheDocument()
  })

  it('renders the balances returned by the API and navigates without a reload', async () => {
    serve({
      '/api/v1/health': health,
      '/api/v1/overview': overview,
      '/api/v1/portfolio': portfolio,
      '/api/v1/events': [],
    })
    mount('/')
    const research = await screen.findByRole('article', { name: 'Research events' })
    expect(within(research).getByText('17')).toBeVisible()
    expect(screen.getByRole('article', { name: 'Mean Brier score' })).toHaveTextContent('0.1234')
    fireEvent.click(screen.getByRole('link', { name: 'Paper Portfolio' }))
    expect(window.location.pathname).toBe('/portfolio')
    expect(await screen.findByRole('article', { name: 'Starting cash' })).toHaveTextContent(
      '$9,007,199,254,740,993.01',
    )
    expect(screen.getByRole('article', { name: 'Current paper cash' })).toHaveTextContent(
      '$9,007,199,254,740,993.01',
    )
  })

  it('shows an empty explorer only after a successful empty response', async () => {
    serve({ '/api/v1/health': health, '/api/v1/events': [] })
    mount('/markets')
    expect(await screen.findByText('No events available')).toBeVisible()
    expect(screen.queryByText(/data unavailable/i)).not.toBeInTheDocument()
  })

  it('distinguishes an uninitialized paper ledger from a zero balance', async () => {
    const detail = 'Paper ledger has not been initialized. Run ingest.'
    serve({
      '/api/v1/health': { ...health, source_status: 'uninitialized' },
      '/api/v1/portfolio': Response.json({ detail }, { status: 404 }),
    })
    mount('/portfolio')
    expect(await screen.findByRole('heading', { name: 'Portfolio uninitialized' })).toBeVisible()
    expect(screen.getByText(detail)).toBeVisible()
    expect(screen.queryByRole('article', { name: 'Current paper cash' })).not.toBeInTheDocument()
  })

  it('makes the missing forecast explicit during event inspection', async () => {
    serve({
      '/api/v1/health': health,
      '/api/v1/events': [incomplete],
      '/api/v1/events/missing-source': incomplete,
    })
    mount('/markets')
    fireEvent.click(await screen.findByRole('button', { name: incomplete.title }))
    expect(await screen.findByRole('heading', { name: incomplete.title })).toBeVisible()
    expect(await screen.findByText(/missing input.*source was unavailable/i)).toBeVisible()
    expect(screen.getByText('Unresolved')).toBeVisible()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('marks a cached snapshot stale when a subsequent refresh fails', async () => {
    const fetch = serve({ '/api/v1/health': health, '/api/v1/events': [] })
    const client = mount('/markets')
    expect(await screen.findByText('No events available')).toBeVisible()
    fetch.mockRejectedValue(new TypeError('Backend stopped'))
    await act(async () => {
      await client.refetchQueries({ type: 'active' })
    })
    expect((await screen.findAllByText(/stale data/i))[0]).toBeVisible()
  })

  it('renders database diagnostics returned by a reachable HTTP 503 backend', async () => {
    const diagnostics: Health = {
      ...health,
      source_status: 'unavailable',
      database: 'unavailable',
      missing_inputs: null,
      warnings: ['Database integrity check failed'],
      last_ingestion_at: null,
      last_evaluation_at: null,
    }
    serve({ '/api/v1/health': Response.json(diagnostics, { status: 503 }) })
    mount('/health')
    expect(await screen.findByText('Database integrity check failed')).toBeVisible()
    expect(screen.getByText('Version')).toBeVisible()
  })
})
