import type { Env } from '../src/types.ts'

/**
 * Test doubles for the Worker's bindings.
 *
 * Deliberately hand written rather than pulled from a Workers test pool. The
 * Worker only touches Request, Response, D1 and a fetch to Resend, all of
 * which Node 24 either has natively or can stub, so the suite runs with zero
 * extra dependencies and in well under a second.
 */

export type Query = { sql: string; binds: unknown[] }

export type D1Row = Record<string, unknown>

/** Canned results, keyed by a substring of the SQL that identifies the query. */
export type D1Canned = { match: string; all?: D1Row[]; first?: D1Row | null }

export class FakeD1 {
  /** Every query the Worker ran, in order. Assert against this. */
  readonly queries: Query[] = []
  // A plain field, not a constructor parameter property. Node's strip-only
  // TypeScript mode rejects parameter properties, since erasing them would
  // change runtime behaviour rather than just remove types.
  private readonly canned: D1Canned[]
  constructor(canned: D1Canned[] = []) {
    this.canned = canned
  }

  prepare(sql: string) {
    const record: Query = { sql, binds: [] }
    const self = this
    const stmt = {
      bind(...binds: unknown[]) {
        record.binds = binds
        return stmt
      },
      async all() {
        self.queries.push(record)
        return { results: self.lookup(sql)?.all ?? [] }
      },
      async first() {
        self.queries.push(record)
        const hit = self.lookup(sql)
        return hit && 'first' in hit ? hit.first : null
      },
      async run() {
        self.queries.push(record)
        return { success: true }
      },
    }
    return stmt
  }

  private lookup(sql: string) {
    return this.canned.find((c) => sql.includes(c.match))
  }

  /** Rows written by INSERT, which is how analytics events are recorded. */
  inserts() {
    return this.queries.filter((q) => q.sql.trim().toUpperCase().startsWith('INSERT'))
  }
}

export type FakeEnvOptions = {
  db?: FakeD1 | null
  statsKey?: string
  statsPassword?: string
  assetBody?: string
  assetStatus?: number
  assetHeaders?: Record<string, string>
}

export function fakeEnv(o: FakeEnvOptions = {}): Env {
  const db = o.db === null ? undefined : (o.db ?? new FakeD1())
  // One cast at the boundary: these doubles implement the slice of each
  // binding the Worker actually calls, not the full runtime interface.
  return {
    ANALYTICS_DB: db,
    STATS_KEY: o.statsKey ?? 'test-key',
    STATS_PASSWORD: o.statsPassword ?? 'test-password',
    RESEND_API_KEY: 'test-resend-key',
    ASSETS: {
      async fetch() {
        return new Response(o.assetBody ?? '<!doctype html><title>asset</title>', {
          status: o.assetStatus ?? 200,
          headers: { 'Content-Type': 'text/html', ...(o.assetHeaders ?? {}) },
        })
      },
    },
  } as unknown as Env
}

/** Collects waitUntil promises so a test can await the fire and forget writes. */
export function fakeCtx() {
  const pending: Promise<unknown>[] = []
  return {
    waitUntil(p: Promise<unknown>) {
      pending.push(p)
    },
    async settle() {
      await Promise.allSettled(pending)
    },
  }
}

export function req(path: string, init: RequestInit & { headers?: Record<string, string> } = {}) {
  return new Request(`https://comprsly.com${path}`, init)
}

/** Parses Set-Cookie into name, value and its flags. */
export function parseCookie(header: string | null) {
  if (!header) return null
  const [pair, ...attrs] = header.split(';').map((s) => s.trim())
  const eq = (pair ?? '').indexOf('=')
  return {
    name: (pair ?? '').slice(0, eq),
    value: decodeURIComponent((pair ?? '').slice(eq + 1)),
    attrs: attrs.map((a) => a.toLowerCase()),
  }
}
