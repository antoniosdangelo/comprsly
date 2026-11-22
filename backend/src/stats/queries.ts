import type { D1Database } from '../types.ts'

export const DAY = 86400000

export type EventTotals = { pageview: number; download_click: number }
export type DailyPoint = { date: string; pageviews: number; downloadClicks: number }

/** Event counts since a timestamp, or all time when `sinceTs` is null. */
export async function totalsSince(db: D1Database, sinceTs: number | null): Promise<EventTotals> {
  const query = sinceTs
    ? db.prepare('SELECT event, COUNT(*) as count FROM events WHERE ts >= ? GROUP BY event').bind(sinceTs)
    : db.prepare('SELECT event, COUNT(*) as count FROM events GROUP BY event')
  const { results } = await query.all<{ event: string; count: number }>()
  const out: EventTotals = { pageview: 0, download_click: 0 }
  for (const row of results) {
    if (row.event === 'pageview' || row.event === 'download_click') out[row.event] = row.count
  }
  return out
}

/**
 * Always exactly 30 points, oldest first, zero filled. The chart depends on a
 * fixed-length series, so a quiet day has to appear as a zero rather than
 * going missing.
 */
export async function dailySeries(db: D1Database, now: number): Promise<DailyPoint[]> {
  const { results } = await db
    .prepare(
      `SELECT strftime('%Y-%m-%d', ts / 1000, 'unixepoch') as day, event, COUNT(*) as count
       FROM events WHERE ts >= ? GROUP BY day, event ORDER BY day ASC`,
    )
    .bind(now - 30 * DAY)
    .all<{ day: string; event: string; count: number }>()

  const byDay: Record<string, EventTotals> = {}
  for (const row of results) {
    const day = (byDay[row.day] ??= { pageview: 0, download_click: 0 })
    if (row.event === 'pageview' || row.event === 'download_click') day[row.event] = row.count
  }

  const out: DailyPoint[] = []
  for (let i = 29; i >= 0; i--) {
    const date = new Date(now - i * DAY).toISOString().slice(0, 10)
    const row = byDay[date] ?? { pageview: 0, download_click: 0 }
    out.push({ date, pageviews: row.pageview, downloadClicks: row.download_click })
  }
  return out
}

/** Average engaged seconds over 30 days, or null when there are no samples. */
export async function avgSessionSeconds(db: D1Database, now: number): Promise<number | null> {
  const row = await db
    .prepare("SELECT AVG(value) as avg, COUNT(*) as n FROM events WHERE event = 'session_duration' AND ts >= ?")
    .bind(now - 30 * DAY)
    .first<{ avg: number | null; n: number }>()
  return row && row.n > 0 && row.avg !== null ? Math.round(row.avg) : null
}

async function topBy(db: D1Database, column: 'referrer' | 'country', now: number) {
  const { results } = await db
    .prepare(
      `SELECT ${column}, COUNT(*) as count FROM events
       WHERE ts >= ? AND event = 'pageview' GROUP BY ${column} ORDER BY count DESC LIMIT 10`,
    )
    .bind(now - 30 * DAY)
    .all()
  return results
}

export const topReferrers = (db: D1Database, now: number) => topBy(db, 'referrer', now)
export const topCountries = (db: D1Database, now: number) => topBy(db, 'country', now)
