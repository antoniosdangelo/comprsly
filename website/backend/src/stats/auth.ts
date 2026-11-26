import type { Env } from '../types.ts'

export const COOKIE_NAME = 'comprsly_stats_auth'
export const COOKIE_MAX_AGE = 60 * 60 * 24 * 30 // 30 days

export function getCookie(request: Request, name: string): string | null {
  const header = request.headers.get('Cookie') ?? ''
  const match = header.match(new RegExp('(?:^|;\s*)' + name + '=([^;]+)'))
  return match?.[1] ? decodeURIComponent(match[1]) : null
}

/**
 * Accepts either a valid session cookie from the login form, or the
 * long-lived ?key= link, which is kept working for bookmarked access.
 *
 * With no STATS_KEY configured, nobody is authorised. Fail closed.
 */
export function isAuthed(request: Request, env: Env, url: URL): boolean {
  if (!env.STATS_KEY) return false
  if (url.searchParams.get('key') === env.STATS_KEY) return true
  return getCookie(request, COOKIE_NAME) === env.STATS_KEY
}

export function sessionCookie(value: string): string {
  return `${COOKIE_NAME}=${encodeURIComponent(value)}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`
}

export function clearedCookie(): string {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`
}
