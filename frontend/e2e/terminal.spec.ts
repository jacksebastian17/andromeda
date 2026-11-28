import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

interface EventSummary {
  id: string
  title: string
  contracts: { label: string }[]
}

interface Overview {
  counts: { events: number; contracts: number; forecasts: number; evaluated_forecasts: number }
  mean_brier: number
}

function cashLabel(amount: string) {
  const [dollars, cents] = amount.split('.')
  return '$' + BigInt(dollars).toLocaleString('en-US') + '.' + cents
}

async function capture(page: Page, name: string) {
  const directory = resolve('test-results', 'screenshots')
  await mkdir(directory, { recursive: true })
  const path = resolve(directory, `${name}.png`)
  await page.screenshot({ path, fullPage: true, animations: 'disabled' })
  await test.info().attach(name, { path, contentType: 'image/png' })
}

async function navigate(page: Page, title: string, pathname: string) {
  await page.getByRole('link', { name: title, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`${pathname}$`))
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
}

test('five pages present the persisted research fixture', async ({ page, request }) => {
  const api = 'http://127.0.0.1:8000/api/v1'
  const overviewResponse = await request.get(`${api}/overview`)
  expect(overviewResponse.status(), 'Migrate and ingest fixtures before running this suite').toBe(
    200,
  )
  const overview: Overview = await overviewResponse.json()
  expect(overview.counts).toMatchObject({
    events: 5,
    contracts: 13,
    forecasts: 10,
    evaluated_forecasts: 7,
    unresolved_forecasts: 3,
    missing_forecasts: 3,
    invalid_forecasts: 0,
  })
  expect(overview.mean_brier).toBeCloseTo(0.7025 / 7, 12)

  const pageErrors: Error[] = []
  const externalRequests = new Set<string>()
  const apiMethods = new Set<string>()
  page.on('pageerror', (error) => pageErrors.push(error))
  page.on('request', (req) => {
    const url = new URL(req.url())
    if (!['http:', 'https:'].includes(url.protocol)) return
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) externalRequests.add(url.origin)
    if (url.pathname.startsWith('/api/')) apiMethods.add(req.method())
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Research events' })).toContainText('5')
  await expect(page.getByRole('article', { name: 'Mean Brier score' })).toContainText(
    overview.mean_brier.toFixed(4),
  )
  await capture(page, 'overview')

  await navigate(page, 'Market Explorer', '/markets')
  const eventResponse = await request.get(`${api}/events`)
  expect(eventResponse.ok()).toBeTruthy()
  const events: EventSummary[] = await eventResponse.json()
  const selected = events.find((event) => event.id === 'T-ASTER')
  if (!selected) throw new Error('Expected synthetic event T-ASTER')
  expect(selected.title).toBe('Aster Reach daily high')
  expect(selected.contracts).toHaveLength(3)
  const search = page.getByRole('searchbox', { name: 'Search events and contracts' })
  await search.fill(selected.title)
  await expect(page.getByText(selected.title, { exact: true }).first()).toBeVisible()
  await search.fill('fixture-name-with-no-match')
  await expect(page.getByText('No matching events', { exact: true })).toBeVisible()
  await search.fill('')
  await expect(page.getByText(selected.title, { exact: true }).first()).toBeVisible()
  await capture(page, 'market-explorer')
  await page.getByRole('button', { name: selected.title, exact: true }).click()
  await expect(page.getByRole('heading', { name: selected.title, exact: true })).toBeVisible()
  for (const contract of selected.contracts) {
    await expect(page.getByText(contract.label, { exact: true }).first()).toBeVisible()
  }
  await capture(page, 'event-detail')

  await navigate(page, 'Research Lab', '/research')
  const models = await request.get(`${api}/research/models`)
  expect(models.ok()).toBeTruthy()
  const [model] = await models.json()
  await expect(page.getByRole('heading', { name: model.id, exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Evaluated forecasts' })).toContainText(
    '3 scored events',
  )
  await expect(
    page.getByText(overview.mean_brier.toFixed(4), { exact: true }).first(),
  ).toBeVisible()
  await capture(page, 'research-lab')

  await navigate(page, 'Paper Portfolio', '/portfolio')
  const cashResponse = await request.get(`${api}/portfolio`)
  expect(cashResponse.ok()).toBeTruthy()
  const cash = await cashResponse.json()
  await expect(page.getByRole('article', { name: 'Current paper cash' })).toContainText(
    cashLabel(cash.current_cash),
  )
  await expect(page.getByRole('article', { name: 'Starting cash' })).toContainText(
    cashLabel(cash.starting_cash),
  )
  await capture(page, 'paper-portfolio')

  await navigate(page, 'System Health', '/health')
  const observerPanel = page.getByRole('region', { name: 'Genuine NBA market observer' })
  await expect(observerPanel).toBeVisible()
  const observerResponse = await request.get(`${api}/observer`)
  expect(observerResponse.ok()).toBeTruthy()
  const campaigns: { deadline: string | null; state: string }[] = await observerResponse.json()
  const started = campaigns.filter((campaign) => campaign.deadline !== null)
  if (started.length === 0) {
    await expect(observerPanel).toContainText('No local campaign has started')
  } else {
    for (const campaign of started) await expect(observerPanel).toContainText(campaign.state)
    await expect(observerPanel).toContainText('GET attempts')
  }
  const healthResponse = await request.get(`${api}/health`)
  expect(healthResponse.ok()).toBeTruthy()
  const health = await healthResponse.json()
  expect(health.missing_inputs).toBe(1)
  await expect(page.getByRole('article', { name: 'Synthetic source' })).toContainText(
    '1 missing input',
  )
  await expect(page.getByText('Version', { exact: true })).toBeVisible()
  await expect(
    page.getByText(new RegExp(health.version.replaceAll('.', '\\.'))).first(),
  ).toBeVisible()
  await capture(page, 'system-health')
  expect(pageErrors).toEqual([])
  expect([...externalRequests]).toEqual([])
  expect([...apiMethods]).toEqual(['GET'])
})

test('a failed poll withdraws existing values and reconnecting restores the snapshot', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('article', { name: 'Research events' })).toContainText('5')
  await page.route('**/api/v1/**', (route) => route.abort('connectionrefused'))
  await expect(page.getByText(/stale data/i).first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('article', { name: 'Research events' })).toHaveCount(0)
  await expect(page.getByText('Disconnected', { exact: true })).toBeVisible()
  await page.unroute('**/api/v1/**')
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect(page.getByRole('article', { name: 'Research events' })).toContainText('5')
  await expect(page.getByText('Backend connected', { exact: true })).toBeVisible()
})

test('the explorer fits a narrow viewport with its detail controls accessible', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/markets')
  const search = page.getByRole('searchbox', { name: 'Search events and contracts' })
  await search.fill('Cirrus')
  await page.getByRole('button', { name: 'Cirrus Bay daily high' }).click()
  await expect(page.getByRole('heading', { name: 'Cirrus Bay daily high' })).toBeVisible()
  await expect(page.getByText(/missing input/i).first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
