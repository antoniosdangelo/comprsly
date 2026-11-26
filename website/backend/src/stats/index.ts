import { getStoreFailures, getStoreInstalls, getStoreRatings, getStoreReviews, getStoreUsage } from '../store-analytics.ts'
import type { Env } from '../types.ts'
import { clearedCookie, COOKIE_NAME, getCookie, isAuthed, sessionCookie } from './auth.ts'
import { DASHBOARD_HTML, LOGIN_HTML } from './html.ts'
import { avgSessionSeconds, DAY, dailySeries, topCountries, topReferrers, totalsSince } from './queries.ts'

const JSON_HEADERS = { 'Content-Type': 'application/json' }
const HTML_HEADERS = { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' }

export async function handleStatsApi(request: Request, env: Env, url: URL): Promise<Response> {
  if (!isAuthed(request, env, url)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 403, headers: JSON_HEADERS })
  }

  const db = env.ANALYTICS_DB
  if (!db) {
    return new Response(JSON.stringify({ error: 'no database bound' }), { status: 503, headers: JSON_HEADERS })
  }

  const now = Date.now()
  const [last24h, last7d, last30d, allTime, storeInstalls, storeUsage, storeRatings, storeReviews, storeFailures, avgSession] =
    await Promise.all([
      totalsSince(db, now - DAY),
      totalsSince(db, now - 7 * DAY),
      totalsSince(db, now - 30 * DAY),
      totalsSince(db, null),
      getStoreInstalls(env),
      getStoreUsage(env),
      getStoreRatings(env),
      getStoreReviews(env),
      getStoreFailures(env),
      avgSessionSeconds(db, now),
    ])

  const body = {
    totals: {
      pageviews: {
        last24h: last24h.pageview, last7d: last7d.pageview,
        last30d: last30d.pageview, allTime: allTime.pageview,
      },
      downloadClicks: {
        last24h: last24h.download_click, last7d: last7d.download_click,
        last30d: last30d.download_click, allTime: allTime.download_click,
      },
    },
    daily: await dailySeries(db, now),
    topReferrers: await topReferrers(db, now),
    topCountries: await topCountries(db, now),
    storeInstalls, storeUsage, storeRatings, storeReviews, storeFailures,
    avgSessionSeconds: avgSession,
    generatedAt: now,
  }

  return new Response(JSON.stringify(body), {
    headers: { ...JSON_HEADERS, 'Cache-Control': 'no-store' },
  })
}

export function handleStatsPage(request: Request, env: Env, url: URL): Response {
  if (!isAuthed(request, env, url)) {
    return new Response(LOGIN_HTML, { headers: HTML_HEADERS })
  }
  const headers: Record<string, string> = { ...HTML_HEADERS }
  // Arriving via ?key= also plants the session cookie, so a later plain visit
  // to comprsly.com/stats just works without retyping anything.
  if (url.searchParams.get('key') === env.STATS_KEY && getCookie(request, COOKIE_NAME) !== env.STATS_KEY) {
    headers['Set-Cookie'] = sessionCookie(env.STATS_KEY as string)
  }
  return new Response(DASHBOARD_HTML, { headers })
}

export async function handleStatsLogin(request: Request, env: Env): Promise<Response> {
  const form = await request.formData()
  const password = String(form.get('password') ?? '')
  if (env.STATS_PASSWORD && password === env.STATS_PASSWORD) {
    return new Response(null, {
      status: 302,
      headers: { Location: '/stats', 'Set-Cookie': sessionCookie(env.STATS_KEY ?? '') },
    })
  }
  return new Response(null, { status: 302, headers: { Location: '/stats?error=1' } })
}

export function handleStatsLogout(): Response {
  return new Response(null, {
    status: 302,
    headers: { Location: '/stats', 'Set-Cookie': clearedCookie() },
  })
}
