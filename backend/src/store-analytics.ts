import type { Env } from './types.ts'

/**
 * Microsoft Partner Center analytics, cached in D1.
 *
 * Converted from JavaScript. Every function body is unchanged; only
 * signatures gained types, because this talks to an external API whose
 * response shapes are not ours to guarantee.
 */

/** Whatever Partner Center returns. Narrowed at each use site, not up front. */
type Json = any

type CacheKey = 'installs' | 'usage' | 'ratings' | 'reviews' | 'failures'

const DAY = 86400000;
const STORE_APP_ID = "9N8W5HPJ4DHV";

// Microsoft's analytics API rate-limits back-to-back calls (confirmed live:
// hitting 4 endpoints in immediate succession returned 429s). This delay
// between calls in the scheduled refresh keeps a full cache refresh well
// clear of that limit. The dashboard itself never calls the Store API
// directly — it only ever reads the cache — so this pacing is the only
// place that matters.
const CALL_GAP_MS = 2500;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function fmtDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

async function getStoreToken(env: Env): Promise<string> {
  const res = await fetch(`https://login.microsoftonline.com/${env.MSSTORE_TENANT_ID}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded; charset=utf-8" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: env.MSSTORE_CLIENT_ID!,
      client_secret: env.MSSTORE_CLIENT_SECRET!,
      resource: "https://manage.devcenter.microsoft.com"
    })
  });
  if (!res.ok) throw new Error(`token request failed: ${res.status}`);
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

async function callApi(token: string, path: string, params: Record<string, string | number>): Promise<Json> {
  const url = `https://manage.devcenter.microsoft.com/v1.0/my/analytics/${path}?${new URLSearchParams(params as Record<string, string>)}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`${path} request failed: ${res.status}`);
  return res.json() as Promise<Json>;
}

function buildInstalls(body: Json, now: number) {
  const byDay: Record<string, number> = {};
  for (const row of body.Value || []) {
    const day = row.date.slice(0, 10);
    byDay[day] = (byDay[day] || 0) + (row.acquisitionQuantity || 0);
  }
  const daily: { date: string; installs: number }[] = [];
  for (let i = 29; i >= 0; i--) {
    const key = fmtDate(new Date(now - i * DAY));
    daily.push({ date: key, installs: byDay[key] || 0 });
  }
  const sumSince = (sinceTs: number) => {
    const cutoff = fmtDate(new Date(sinceTs));
    return Object.entries(byDay).filter(([day]) => day >= cutoff).reduce((a, [, n]) => a + (n as number), 0);
  };
  return {
    totals: {
      last24h: sumSince(now - DAY),
      last7d: sumSince(now - 7 * DAY),
      last30d: sumSince(now - 30 * DAY),
      allTime: Object.values(byDay).reduce((a, n) => a + n, 0)
    },
    daily
  };
}

function buildUsage(body: Json, now: number) {
  const byDay: Record<string, { activeDevices: number; sessions: number; engagementMinutes: number }> = {};
  for (const row of body.Value || []) {
    const day = row.date.slice(0, 10);
    byDay[day] = byDay[day] || { activeDevices: 0, sessions: 0, engagementMinutes: 0 };
    byDay[day].activeDevices += row.dailyActiveDevices || 0;
    byDay[day].sessions += row.dailySessionCount || 0;
    byDay[day].engagementMinutes += row.engagementDurationMinutes || 0;
  }
  const daily = [];
  for (let i = 29; i >= 0; i--) {
    const key = fmtDate(new Date(now - i * DAY));
    const d = byDay[key] || { activeDevices: 0, sessions: 0, engagementMinutes: 0 };
    daily.push({ date: key, activeDevices: d.activeDevices, sessions: d.sessions });
  }
  const last7 = daily.slice(-7).reduce((a, d) => a + d.activeDevices, 0);
  const last30 = daily.reduce((a, d) => a + d.activeDevices, 0);
  const totalSessions = daily.reduce((a, d) => a + d.sessions, 0);
  const totalMinutes = Object.values(byDay).reduce((a, d) => a + d.engagementMinutes, 0);
  return {
    activeDevicesLast7d: last7,
    activeDevicesLast30d: last30,
    avgSessionMinutes: totalSessions > 0 ? +(totalMinutes / totalSessions).toFixed(1) : 0,
    daily
  };
}

function buildRatings(body: Json) {
  const totals = { oneStar: 0, twoStars: 0, threeStars: 0, fourStars: 0, fiveStars: 0 };
  for (const row of body.Value || []) {
    totals.oneStar += row.oneStar || 0;
    totals.twoStars += row.twoStars || 0;
    totals.threeStars += row.threeStars || 0;
    totals.fourStars += row.fourStars || 0;
    totals.fiveStars += row.fiveStars || 0;
  }
  const count = totals.oneStar + totals.twoStars + totals.threeStars + totals.fourStars + totals.fiveStars;
  const sum = totals.oneStar * 1 + totals.twoStars * 2 + totals.threeStars * 3 + totals.fourStars * 4 + totals.fiveStars * 5;
  return { ...totals, count, average: count > 0 ? +(sum / count).toFixed(2) : null };
}

function buildReviews(body: Json) {
  return (body.Value || [])
    .slice(0, 20)
    .map((r: Json) => ({
      date: r.date,
      market: r.market || null,
      rating: r.rating,
      title: r.reviewTitle || "",
      text: r.reviewText || "",
      reviewer: r.reviewerName || "Anonymous"
    }));
}

function buildFailures(body: Json) {
  const byType: Record<string, { count: number; eventType: string }> = {};
  let totalDevices = 0;
  for (const row of body.Value || []) {
    const name = row.failureName || "Unknown failure";
    byType[name] = byType[name] || { count: 0, eventType: row.eventType || "unknown" };
    byType[name].count += row.deviceCount || 0;
    totalDevices += row.deviceCount || 0;
  }
  const top = Object.entries(byType)
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 10)
    .map(([name, v]) => ({ name, count: Math.round(v.count * 10) / 10, eventType: v.eventType }));
  return { totalDevicesAffected: Math.round(totalDevices * 10) / 10, top };
}

async function cacheSet(env: Env, key: CacheKey, data: unknown): Promise<void> {
  await env.ANALYTICS_DB!.prepare(
    "INSERT INTO store_cache (key, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at"
  ).bind(key, JSON.stringify(data), Date.now()).run();
}

async function cacheGet(env: Env, key: CacheKey) {
  const row = await env.ANALYTICS_DB!.prepare("SELECT data, updated_at FROM store_cache WHERE key = ?").bind(key).first<{ data: string; updated_at: number }>();
  if (!row) return null;
  try {
    return { data: JSON.parse(row.data), updatedAt: row.updated_at };
  } catch {
    return null;
  }
}

// Called on a schedule (see the `scheduled` export in index.js), never from
// a live page request — this is the only place that talks to the Store API.
export async function refreshStoreCache(env: Env): Promise<void> {
  if (!env.MSSTORE_TENANT_ID || !env.MSSTORE_CLIENT_ID || !env.MSSTORE_CLIENT_SECRET) return;

  try {
    const token = await getStoreToken(env);
    const now = Date.now();
    const startDate180 = fmtDate(new Date(now - 180 * DAY));
    const startDate30 = fmtDate(new Date(now - 30 * DAY));
    const endDate = fmtDate(new Date(now));

    const acquisitions = await callApi(token, "appacquisitions", {
      applicationId: STORE_APP_ID, startDate: startDate180, endDate, top: 10000, skip: 0
    });
    await cacheSet(env, "installs", buildInstalls(acquisitions, now));
    await sleep(CALL_GAP_MS);

    const usage = await callApi(token, "usagedaily", {
      applicationId: STORE_APP_ID, startDate: startDate30, endDate
    });
    await cacheSet(env, "usage", buildUsage(usage, now));
    await sleep(CALL_GAP_MS);

    const ratings = await callApi(token, "ratings", {
      applicationId: STORE_APP_ID, startDate: startDate180, endDate, top: 10000, skip: 0
    });
    await cacheSet(env, "ratings", buildRatings(ratings));
    await sleep(CALL_GAP_MS);

    const reviews = await callApi(token, "reviews", {
      applicationId: STORE_APP_ID, startDate: startDate180, endDate, top: 20, skip: 0, orderby: "date desc"
    });
    await cacheSet(env, "reviews", buildReviews(reviews));
    await sleep(CALL_GAP_MS);

    const failures = await callApi(token, "failurehits", {
      applicationId: STORE_APP_ID, startDate: startDate30, endDate, top: 10000, skip: 0
    });
    await cacheSet(env, "failures", buildFailures(failures));
  } catch (err) {
    console.error("Store cache refresh failed:", err);
  }
}

export async function getStoreInstalls(env: Env): Promise<unknown> {
  const cached = await cacheGet(env, "installs");
  return cached ? cached.data : null;
}

export async function getStoreUsage(env: Env): Promise<unknown> {
  const cached = await cacheGet(env, "usage");
  return cached ? cached.data : null;
}

export async function getStoreRatings(env: Env): Promise<unknown> {
  const cached = await cacheGet(env, "ratings");
  return cached ? cached.data : null;
}

export async function getStoreReviews(env: Env): Promise<unknown> {
  const cached = await cacheGet(env, "reviews");
  return cached ? cached.data : null;
}

export async function getStoreFailures(env: Env): Promise<unknown> {
  const cached = await cacheGet(env, "failures");
  return cached ? cached.data : null;
}
