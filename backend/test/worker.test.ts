import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import worker from '../src/index.js'
import { FakeD1, fakeCtx, fakeEnv, parseCookie, req } from './helpers.ts'

/**
 * CHARACTERISATION TESTS.
 *
 * These pin what the Worker does TODAY, bugs and quirks included, so the
 * TypeScript reorganisation can be proven to change nothing for users. If one
 * of these fails after a refactor, the refactor is wrong, not the test.
 *
 * Written against the original JavaScript before any files moved.
 */

const STORE_URL = 'https://apps.microsoft.com/detail/9N8W5HPJ4DHV'

const SECURITY_HEADERS: Record<string, string> = {
  'strict-transport-security': 'max-age=31536000; includeSubDomains; preload',
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'SAMEORIGIN',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'permissions-policy': 'camera=(), microphone=(), geolocation=()',
}

describe('static pages', () => {
  it('serves the asset and adds all five security headers', async () => {
    const ctx = fakeCtx()
    const res = await worker.fetch(req('/'), fakeEnv(), ctx)
    assert.equal(res.status, 200)
    for (const [header, value] of Object.entries(SECURITY_HEADERS)) {
      assert.equal(res.headers.get(header), value, `missing or wrong: ${header}`)
    }
  })

  it('does NOT set a Content-Security-Policy', async () => {
    // Deliberate, recorded in Build.md: the page's inline styles and handlers
    // would break under any strict CSP. Pinned so nobody adds one by reflex.
    const res = await worker.fetch(req('/'), fakeEnv(), fakeCtx())
    assert.equal(res.headers.get('content-security-policy'), null)
  })

  it('preserves the asset status, so a 404 stays a 404', async () => {
    const res = await worker.fetch(req('/nope'), fakeEnv({ assetStatus: 404 }), fakeCtx())
    assert.equal(res.status, 404)
  })
})

describe('pageview tracking', () => {
  for (const path of ['/', '/privacy', '/privacy/']) {
    it(`logs a pageview for ${path}`, async () => {
      const db = new FakeD1()
      const ctx = fakeCtx()
      await worker.fetch(req(path), fakeEnv({ db }), ctx)
      await ctx.settle()
      const rows = db.inserts()
      assert.equal(rows.length, 1)
      assert.equal(rows[0]?.binds[1], 'pageview')
      assert.equal(rows[0]?.binds[2], path)
    })
  }

  it('does not log a pageview for any other path', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    await worker.fetch(req('/favicon.ico'), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(db.inserts().length, 0)
  })

  it('does not log a pageview for a non GET request', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    await worker.fetch(req('/', { method: 'POST' }), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(db.inserts().length, 0)
  })

  it('records the referrer hostname, and "direct" when absent or unparseable', async () => {
    const cases: [Record<string, string>, string][] = [
      [{ Referer: 'https://news.ycombinator.com/item?id=1' }, 'news.ycombinator.com'],
      [{}, 'direct'],
      [{ Referer: 'not a url' }, 'direct'],
    ]
    for (const [headers, expected] of cases) {
      const db = new FakeD1()
      const ctx = fakeCtx()
      await worker.fetch(req('/', { headers }), fakeEnv({ db }), ctx)
      await ctx.settle()
      assert.equal(db.inserts()[0]?.binds[3], expected)
    }
  })

  it('drops known bot traffic instead of polluting the funnel', async () => {
    for (const ua of ['Googlebot/2.1', 'curl/8.4.0', 'python-requests/2.31', 'HeadlessChrome/120']) {
      const db = new FakeD1()
      const ctx = fakeCtx()
      await worker.fetch(req('/', { headers: { 'User-Agent': ua } }), fakeEnv({ db }), ctx)
      await ctx.settle()
      assert.equal(db.inserts().length, 0, `${ua} should have been filtered`)
    }
  })

  it('survives having no database bound', async () => {
    const ctx = fakeCtx()
    const res = await worker.fetch(req('/'), fakeEnv({ db: null }), ctx)
    await ctx.settle()
    assert.equal(res.status, 200)
  })
})

describe('/go/store', () => {
  it('redirects to the Store listing', async () => {
    const res = await worker.fetch(req('/go/store'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 302)
    assert.equal(res.headers.get('location'), STORE_URL)
  })

  it('logs a download_click', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    await worker.fetch(req('/go/store'), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(db.inserts()[0]?.binds[1], 'download_click')
  })
})

describe('/api/session-duration', () => {
  const post = (body: unknown) =>
    req('/api/session-duration', {
      method: 'POST',
      body: typeof body === 'string' ? body : JSON.stringify(body),
    })

  it('accepts a beacon and answers 204 with no body', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    const res = await worker.fetch(post({ seconds: 42, path: '/' }), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(res.status, 204)
    assert.equal(await res.text(), '')
    const row = db.inserts()[0]
    assert.equal(row?.binds[1], 'session_duration')
    assert.equal(row?.binds[5], 42)
  })

  it('clamps to 30 minutes, because anything longer is a forgotten tab', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    await worker.fetch(post({ seconds: 99999 }), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(db.inserts()[0]?.binds[5], 1800)
  })

  it('ignores zero, negative and non numeric durations', async () => {
    for (const seconds of [0, -5, 'abc', null]) {
      const db = new FakeD1()
      const ctx = fakeCtx()
      const res = await worker.fetch(post({ seconds }), fakeEnv({ db }), ctx)
      await ctx.settle()
      assert.equal(res.status, 204)
      assert.equal(db.inserts().length, 0, `seconds=${seconds} should not be recorded`)
    }
  })

  it('defaults a missing path to /', async () => {
    const db = new FakeD1()
    const ctx = fakeCtx()
    await worker.fetch(post({ seconds: 10 }), fakeEnv({ db }), ctx)
    await ctx.settle()
    assert.equal(db.inserts()[0]?.binds[2], '/')
  })

  it('never fails the request on malformed JSON', async () => {
    const ctx = fakeCtx()
    const res = await worker.fetch(post('{ not json'), fakeEnv(), ctx)
    assert.equal(res.status, 204)
  })
})

describe('/stats authentication', () => {
  it('shows the login page when unauthenticated', async () => {
    const res = await worker.fetch(req('/stats'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 200)
    assert.match(res.headers.get('content-type') ?? '', /text\/html/)
    assert.equal(res.headers.get('cache-control'), 'no-store')
    assert.match(await res.text(), /type="password"/)
  })

  it('accepts the ?key= link and plants a session cookie', async () => {
    const res = await worker.fetch(req('/stats?key=test-key'), fakeEnv(), fakeCtx())
    const cookie = parseCookie(res.headers.get('set-cookie'))
    assert.equal(cookie?.name, 'comprsly_stats_auth')
    assert.equal(cookie?.value, 'test-key')
    assert.ok(cookie?.attrs.includes('httponly'))
    assert.ok(cookie?.attrs.includes('secure'))
    assert.ok(cookie?.attrs.includes('samesite=lax'))
  })

  it('accepts the session cookie without a key in the URL', async () => {
    const res = await worker.fetch(
      req('/stats', { headers: { Cookie: 'comprsly_stats_auth=test-key' } }),
      fakeEnv(),
      fakeCtx(),
    )
    const body = await res.text()
    assert.doesNotMatch(body, /type="password"/)
    // Already has the cookie, so it is not re-sent.
    assert.equal(res.headers.get('set-cookie'), null)
  })

  it('rejects a wrong key', async () => {
    const res = await worker.fetch(req('/stats?key=wrong'), fakeEnv(), fakeCtx())
    assert.match(await res.text(), /type="password"/)
  })

  it('denies everyone when STATS_KEY is not configured', async () => {
    const env = { ...fakeEnv(), STATS_KEY: undefined }
    const res = await worker.fetch(req('/stats?key=undefined'), env, fakeCtx())
    assert.match(await res.text(), /type="password"/)
  })
})

describe('/stats/login and /stats/logout', () => {
  const form = (password: string) => {
    const body = new FormData()
    body.set('password', password)
    return req('/stats/login', { method: 'POST', body })
  }

  it('sets the cookie and redirects on the right password', async () => {
    const res = await worker.fetch(form('test-password'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 302)
    assert.equal(res.headers.get('location'), '/stats')
    assert.equal(parseCookie(res.headers.get('set-cookie'))?.value, 'test-key')
  })

  it('redirects back with an error flag on the wrong password', async () => {
    const res = await worker.fetch(form('nope'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 302)
    assert.equal(res.headers.get('location'), '/stats?error=1')
    assert.equal(res.headers.get('set-cookie'), null)
  })

  it('clears the cookie on logout', async () => {
    const res = await worker.fetch(req('/stats/logout'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 302)
    const cookie = parseCookie(res.headers.get('set-cookie'))
    assert.equal(cookie?.value, '')
    assert.ok(cookie?.attrs.includes('max-age=0'))
  })
})

describe('/api/stats', () => {
  it('returns 403 JSON when unauthenticated', async () => {
    const res = await worker.fetch(req('/api/stats'), fakeEnv(), fakeCtx())
    assert.equal(res.status, 403)
    assert.deepEqual(await res.json(), { error: 'unauthorized' })
  })

  it('returns the full payload shape when authenticated', async () => {
    const db = new FakeD1([
      { match: 'GROUP BY event', all: [{ event: 'pageview', count: 7 }, { event: 'download_click', count: 2 }] },
      { match: "event = 'session_duration'", first: { avg: 61.4, n: 3 } },
      { match: 'GROUP BY day, event', all: [] },
      { match: 'GROUP BY referrer', all: [{ referrer: 'direct', count: 7 }] },
      { match: 'GROUP BY country', all: [{ country: 'US', count: 7 }] },
    ])
    const res = await worker.fetch(req('/api/stats?key=test-key'), fakeEnv({ db }), fakeCtx())
    assert.equal(res.status, 200)
    assert.equal(res.headers.get('cache-control'), 'no-store')

    const body = (await res.json()) as Record<string, any>
    assert.deepEqual(Object.keys(body).sort(), [
      'avgSessionSeconds', 'daily', 'generatedAt', 'storeFailures', 'storeInstalls',
      'storeRatings', 'storeReviews', 'storeUsage', 'topCountries', 'topReferrers', 'totals',
    ])
    assert.equal(body.totals.pageviews.allTime, 7)
    assert.equal(body.totals.downloadClicks.allTime, 2)
    // Rounded from the average, not passed through raw.
    assert.equal(body.avgSessionSeconds, 61)
    // Always exactly 30 days, zero filled, oldest first.
    assert.equal(body.daily.length, 30)
    assert.deepEqual(body.daily[0], { date: body.daily[0].date, pageviews: 0, downloadClicks: 0 })
    assert.ok(body.daily[0].date < body.daily[29].date)
  })

  it('reports a null average when there are no session samples', async () => {
    const db = new FakeD1([{ match: "event = 'session_duration'", first: { avg: null, n: 0 } }])
    const res = await worker.fetch(req('/api/stats?key=test-key'), fakeEnv({ db }), fakeCtx())
    assert.equal(((await res.json()) as any).avgSessionSeconds, null)
  })
})
