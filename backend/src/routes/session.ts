import { MAX_SESSION_SECONDS, logEvent } from '../analytics.ts'
import type { Ctx, Env } from '../types.ts'

/**
 * The page's unload beacon. Always answers 204, whatever arrives: a broken
 * beacon must never surface as an error to a visitor who is already leaving.
 */
export async function handleSessionDuration(request: Request, env: Env, ctx: Ctx): Promise<Response> {
  try {
    const body = (await request.json()) as { seconds?: unknown; path?: unknown }
    const seconds = Math.max(0, Math.min(MAX_SESSION_SECONDS, Math.round(Number(body.seconds) || 0)))
    if (seconds > 0) {
      logEvent(env, ctx, {
        event: 'session_duration',
        path: typeof body.path === 'string' ? body.path : '/',
        request,
        value: seconds,
      })
    }
  } catch {
    // Malformed payload. Never worth failing the request over.
  }
  return new Response(null, { status: 204 })
}
