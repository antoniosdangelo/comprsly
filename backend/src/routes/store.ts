import { logEvent } from '../analytics.ts'
import type { Ctx, Env } from '../types.ts'

/**
 * Antonio's call, 2026-07-29: link straight at the Store listing rather than
 * maintain any live-checking logic. It 404'd at the time because certification
 * had not passed; it has since, and the redirect needed no further action.
 */
export const STORE_URL = 'https://apps.microsoft.com/detail/9N8W5HPJ4DHV'

export function handleStoreRedirect(request: Request, env: Env, ctx: Ctx, url: URL): Response {
  logEvent(env, ctx, { event: 'download_click', path: url.pathname, request })
  return Response.redirect(STORE_URL, 302)
}
