/** Shared types for the Worker. Hand written: the Worker touches a small,
    stable slice of the Workers runtime, so a full types package is overkill. */

export type D1Result<T = Record<string, unknown>> = { results: T[] }

export type D1Statement = {
  bind: (...values: unknown[]) => D1Statement
  all: <T = Record<string, unknown>>() => Promise<D1Result<T>>
  first: <T = Record<string, unknown>>() => Promise<T | null>
  run: () => Promise<unknown>
}

export type D1Database = { prepare: (sql: string) => D1Statement }

export type Env = {
  ANALYTICS_DB?: D1Database
  ASSETS: { fetch: (request: Request) => Promise<Response> }
  /** Grants access to /stats and /api/stats. Absent means nobody gets in. */
  STATS_KEY?: string
  /** Checked by the login form, then exchanged for a STATS_KEY cookie. */
  STATS_PASSWORD?: string
  RESEND_API_KEY?: string
  /** Partner Center credentials, used only by the scheduled cache refresh. */
  MSSTORE_TENANT_ID?: string
  MSSTORE_CLIENT_ID?: string
  MSSTORE_CLIENT_SECRET?: string
}

export type Ctx = { waitUntil: (p: Promise<unknown>) => void }

/**
 * An inbound email, as the Worker's email handler receives it. Narrowed to
 * the two fields the relay reads, with `raw` kept as the runtime's own
 * ReadableStream so PostalMime accepts it without a cast.
 */
export type EmailMessage = { raw: ReadableStream<Uint8Array>; from: string }
