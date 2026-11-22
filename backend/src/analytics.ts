import type { Ctx, Env } from './types.ts'

/**
 * Coarse bot filter. Not real bot detection, just cheap noise reduction so
 * crawler traffic does not pollute the funnel numbers.
 */
const BOT_UA = /bot|crawl|spider|slurp|facebookexternalhit|headlesschrome|curl|wget|python-requests/i

/** The only paths whose views are counted. */
export const TRACKED_PATHS: ReadonlySet<string> = new Set(['/', '/privacy', '/privacy/'])

/** A forgotten background tab is not engaged time, so sessions cap at 30 min. */
export const MAX_SESSION_SECONDS = 1800

export type AnalyticsEvent = 'pageview' | 'download_click' | 'session_duration'

/** The referring hostname, or "direct" when there is none or it will not parse. */
export function refererHost(request: Request): string {
  const referer = request.headers.get('Referer')
  if (!referer) return 'direct'
  try {
    return new URL(referer).hostname
  } catch {
    return 'direct'
  }
}

export function isBot(request: Request): boolean {
  return BOT_UA.test(request.headers.get('User-Agent') ?? '')
}

/**
 * Records one event, fire and forget via ctx.waitUntil, so a slow or failing
 * insert never adds latency to the real page response or breaks it.
 */
export function logEvent(
  env: Env,
  ctx: Ctx,
  opts: { event: AnalyticsEvent; path: string; request: Request; value?: number | null },
): void {
  const db = env.ANALYTICS_DB
  if (!db) return
  if (isBot(opts.request)) return

  const cf = (opts.request as Request & { cf?: { country?: string } }).cf
  ctx.waitUntil(
    db
      .prepare('INSERT INTO events (ts, event, path, referrer, country, value) VALUES (?, ?, ?, ?, ?, ?)')
      .bind(Date.now(), opts.event, opts.path, refererHost(opts.request), cf?.country ?? 'XX', opts.value ?? null)
      .run()
      .catch((err: unknown) => console.error('analytics insert failed:', err)),
  )
}
