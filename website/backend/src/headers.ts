/**
 * Security headers applied to EVERY response, static assets included.
 *
 * This is why wrangler.jsonc keeps `run_worker_first: true`. With a narrower
 * setting, asset requests bypass the Worker entirely and silently lose all of
 * these. That cost a day on 2026-07-27 before the flag was found.
 *
 * No Content-Security-Policy, deliberately: the page carries inline styles and
 * inline handlers that any reasonably strict CSP would break, and it takes no
 * user input. Pinned by a test so nobody adds one by reflex.
 */
const SECURITY_HEADERS: Record<string, string> = {
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'SAMEORIGIN',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}

/** Returns a copy of `response` with the security headers added. */
export function withSecurityHeaders(response: Response): Response {
  const headers = new Headers(response.headers)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value)
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}
