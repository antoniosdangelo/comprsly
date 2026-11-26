import { TRACKED_PATHS, logEvent } from './analytics.ts'
import { relayEmail } from './email.ts'
import { withSecurityHeaders } from './headers.ts'
import { handleSessionDuration } from './routes/session.ts'
import { handleStoreRedirect } from './routes/store.ts'
import { handleStatsApi, handleStatsLogin, handleStatsLogout, handleStatsPage } from './stats/index.ts'
import { refreshStoreCache } from './store-analytics.ts'
import type { Ctx, EmailMessage, Env } from './types.ts'

/**
 * comprsly.com.
 *
 * Every request passes through here, static assets included, because that is
 * the only way the security headers get applied. See headers.ts and the
 * run_worker_first note in wrangler.jsonc before changing the asset config.
 */
export default {
  async fetch(request: Request, env: Env, ctx: Ctx): Promise<Response> {
    const url = new URL(request.url)
    const { pathname } = url

    if (pathname === '/api/stats') return handleStatsApi(request, env, url)
    if (pathname === '/stats') return handleStatsPage(request, env, url)
    if (pathname === '/stats/login' && request.method === 'POST') return handleStatsLogin(request, env)
    if (pathname === '/stats/logout') return handleStatsLogout()
    if (pathname === '/api/session-duration' && request.method === 'POST') {
      return handleSessionDuration(request, env, ctx)
    }
    if (pathname === '/go/store') return handleStoreRedirect(request, env, ctx, url)

    if (request.method === 'GET' && TRACKED_PATHS.has(pathname)) {
      logEvent(env, ctx, { event: 'pageview', path: pathname, request })
    }

    return withSecurityHeaders(await env.ASSETS.fetch(request))
  },

  async email(message: EmailMessage, env: Env): Promise<void> {
    await relayEmail(message, env)
  },

  /**
   * Refreshes the Store analytics cache on the schedule in wrangler.jsonc.
   * This is the ONLY place that talks to the Store API, deliberately, to stay
   * clear of its rate limit. /api/stats only ever reads the cache.
   */
  async scheduled(_event: unknown, env: Env, ctx: Ctx): Promise<void> {
    ctx.waitUntil(refreshStoreCache(env))
  },
}
