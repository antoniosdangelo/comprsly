import { getStoreInstalls, getStoreUsage, getStoreRatings, getStoreReviews, getStoreFailures } from "./store-analytics.js";

const DAY = 86400000;
const COOKIE_NAME = "comprsly_stats_auth";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

function getCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  const match = header.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[1]) : null;
}

// Accepts either a valid session cookie (from the login form) or the
// long-lived ?key= link (kept working for direct/bookmarked access).
function isAuthed(request, env, url) {
  if (!env.STATS_KEY) return false;
  if (url.searchParams.get("key") === env.STATS_KEY) return true;
  return getCookie(request, COOKIE_NAME) === env.STATS_KEY;
}

async function totalsSince(db, sinceTs) {
  const query = sinceTs
    ? db.prepare("SELECT event, COUNT(*) as count FROM events WHERE ts >= ? GROUP BY event").bind(sinceTs)
    : db.prepare("SELECT event, COUNT(*) as count FROM events GROUP BY event");
  const { results } = await query.all();
  const out = { pageview: 0, download_click: 0 };
  for (const row of results) out[row.event] = row.count;
  return out;
}

export async function handleStatsApi(request, env, url) {
  if (!isAuthed(request, env, url)) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 403,
      headers: { "Content-Type": "application/json" }
    });
  }

  const db = env.ANALYTICS_DB;
  const now = Date.now();
  const since24h = now - DAY;
  const since7d = now - 7 * DAY;
  const since30d = now - 30 * DAY;

  const [last24h, last7d, last30d, allTime, storeInstalls, storeUsage, storeRatings, storeReviews, storeFailures, avgSessionRow] = await Promise.all([
    totalsSince(db, since24h),
    totalsSince(db, since7d),
    totalsSince(db, since30d),
    totalsSince(db, null),
    getStoreInstalls(env),
    getStoreUsage(env),
    getStoreRatings(env),
    getStoreReviews(env),
    getStoreFailures(env),
    db.prepare("SELECT AVG(value) as avg, COUNT(*) as n FROM events WHERE event = 'session_duration' AND ts >= ?").bind(since30d).first()
  ]);
  const avgSessionSeconds = avgSessionRow && avgSessionRow.n > 0 ? Math.round(avgSessionRow.avg) : null;

  const { results: dailyRows } = await db
    .prepare(
      `SELECT strftime('%Y-%m-%d', ts / 1000, 'unixepoch') as day, event, COUNT(*) as count
       FROM events WHERE ts >= ? GROUP BY day, event ORDER BY day ASC`
    )
    .bind(since30d)
    .all();

  const dayMap = {};
  for (const row of dailyRows) {
    dayMap[row.day] = dayMap[row.day] || { pageview: 0, download_click: 0 };
    dayMap[row.day][row.event] = row.count;
  }
  const daily = [];
  for (let i = 29; i >= 0; i--) {
    const key = new Date(now - i * DAY).toISOString().slice(0, 10);
    const row = dayMap[key] || { pageview: 0, download_click: 0 };
    daily.push({ date: key, pageviews: row.pageview, downloadClicks: row.download_click });
  }

  const { results: topReferrers } = await db
    .prepare(
      `SELECT referrer, COUNT(*) as count FROM events
       WHERE ts >= ? AND event = 'pageview' GROUP BY referrer ORDER BY count DESC LIMIT 10`
    )
    .bind(since30d)
    .all();

  const { results: topCountries } = await db
    .prepare(
      `SELECT country, COUNT(*) as count FROM events
       WHERE ts >= ? AND event = 'pageview' GROUP BY country ORDER BY count DESC LIMIT 10`
    )
    .bind(since30d)
    .all();

  const body = {
    totals: {
      pageviews: {
        last24h: last24h.pageview,
        last7d: last7d.pageview,
        last30d: last30d.pageview,
        allTime: allTime.pageview
      },
      downloadClicks: {
        last24h: last24h.download_click,
        last7d: last7d.download_click,
        last30d: last30d.download_click,
        allTime: allTime.download_click
      }
    },
    daily,
    topReferrers,
    topCountries,
    storeInstalls,
    storeUsage,
    storeRatings,
    storeReviews,
    storeFailures,
    avgSessionSeconds,
    generatedAt: now
  };

  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
  });
}

export function handleStatsPage(request, env, url) {
  if (!isAuthed(request, env, url)) {
    return new Response(LOGIN_HTML, {
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" }
    });
  }
  const headers = { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" };
  // A link visited via ?key= also plants the session cookie, so a plain
  // comprsly.com/stats visit later just works without retyping anything.
  if (url.searchParams.get("key") === env.STATS_KEY && getCookie(request, COOKIE_NAME) !== env.STATS_KEY) {
    headers["Set-Cookie"] =
      `${COOKIE_NAME}=${encodeURIComponent(env.STATS_KEY)}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`;
  }
  return new Response(DASHBOARD_HTML, { headers });
}

export async function handleStatsLogin(request, env) {
  const form = await request.formData();
  const password = form.get("password") || "";
  if (env.STATS_PASSWORD && password === env.STATS_PASSWORD) {
    return new Response(null, {
      status: 302,
      headers: {
        Location: "/stats",
        "Set-Cookie": `${COOKIE_NAME}=${encodeURIComponent(env.STATS_KEY)}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax`
      }
    });
  }
  return new Response(null, { status: 302, headers: { Location: "/stats?error=1" } });
}

export function handleStatsLogout() {
  return new Response(null, {
    status: 302,
    headers: {
      Location: "/stats",
      "Set-Cookie": `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`
    }
  });
}

// Shared head/typography block, copied verbatim from public/privacy/index.html
// so this always tracks the real site's font stack and type scale exactly,
// not a lookalike. color-scheme is forced light with no dark-mode branch, same
// as the rest of the site — this must never follow a viewer's OS/browser theme.
const HEAD = `<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#ffffff">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
  :root { color-scheme: light; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: #ffffff; color: #121212; }
  a { color: #0B0B0D; }
  a:hover { color: #6A6A6A; }
  * { box-sizing: border-box; }
  .wrap { font-family: -apple-system, 'Segoe UI', system-ui, sans-serif; color: #121212; -webkit-font-smoothing: antialiased; }
</style>`;

const LOGIN_HTML = `<!doctype html>
<html lang="en"><head>
${HEAD}
<title>Sign in · Comprsly Analytics</title>
</head>
<body>
<div class="wrap">
  <header style="max-width: 400px; margin: 0 auto; padding: 32px 24px 0;">
    <a href="/" aria-label="Comprsly home" style="display: inline-flex; align-items: center; gap: 10px; text-decoration: none; color: #121212; padding: 10px 4px; margin: -10px -4px;">
      <img src="/privacy/assets/b07c624a68.png" alt="Comprsly" style="width: 22px; height: auto; filter: invert(1); flex-shrink: 0;">
      <span style="font-size: 17px; font-weight: 600; letter-spacing: -0.01em;">Comprsly</span>
    </a>
  </header>
  <main style="max-width: 400px; margin: 0 auto; padding: 44px 24px 64px;">
    <h1 style="font-size: 22px; font-weight: 700; letter-spacing: -0.015em; margin: 0 0 6px;">Analytics sign in</h1>
    <p style="font-size: 14px; color: #6A6A6A; margin: 0 0 24px;">Internal, not indexed. Enter the password to continue.</p>
    <form method="POST" action="/stats/login" style="display: flex; flex-direction: column; gap: 10px;">
      <input type="password" name="password" autofocus placeholder="Password" style="font-size: 15px; padding: 12px 14px; border: 1px solid #E3E3E3; border-radius: 10px; font-family: inherit; outline: none;">
      <button type="submit" style="appearance: none; border: none; background: #0B0B0D; color: #ffffff; font-size: 14px; font-weight: 600; padding: 13px 14px; border-radius: 10px; cursor: pointer;">Sign in</button>
    </form>
    <p id="err" style="display:none; font-size: 13px; color: #3D3D3D; margin: 12px 0 0;">Wrong password, try again.</p>
  </main>
</div>
<script>
if (new URLSearchParams(location.search).get("error")) {
  document.getElementById("err").style.display = "block";
  history.replaceState(null, "", "/stats");
}
</script>
</body>
</html>`;

const DASHBOARD_HTML = `<!doctype html>
<html lang="en"><head>
${HEAD}
<title>Analytics · Comprsly</title>
<style>
  main { max-width: 720px; margin: 0 auto; padding: 0 24px 64px; }
  h1 { font-size: clamp(26px, 6vw, 34px); font-weight: 700; letter-spacing: -0.025em; line-height: 1.1; margin: 28px 0 4px; }
  .sub { font-size: 13px; color: #9A9A9A; margin: 0 0 28px; }
  .sub a, .sub button {
    appearance: none; border: 1px solid #E3E3E3; background: #ffffff; text-decoration: none;
    color: #6A6A6A; font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px;
    cursor: pointer; margin-left: 8px; font-family: inherit; display: inline-block;
  }
  .sub a:hover, .sub button:hover { color: #121212; border-color: #C9C9C9; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 32px; }
  .card { background: #ffffff; border: 1px solid #E3E3E3; border-radius: 14px; padding: 16px 18px; }
  .card .label { font-size: 12px; font-weight: 600; color: #6A6A6A; margin-bottom: 10px; }
  .card .row { display: flex; justify-content: space-between; font-size: 13.5px; color: #3D3D3D; padding: 3px 0; }
  .card .row .n { font-weight: 700; color: #121212; font-variant-numeric: tabular-nums; }
  .card.pageviews .row .n { color: #0B0B0D; }
  .card.downloads .row .n { color: #6A6A6A; }
  section { margin-bottom: 32px; }
  h2 { font-size: 22px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 10px; color: #121212; }
  .hint { font-size: 13px; color: #9A9A9A; margin: -6px 0 14px; }
  .legend { display: flex; gap: 16px; font-size: 12.5px; color: #6A6A6A; margin-bottom: 12px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .swatch { width: 16px; height: 0; border-top-width: 2.5px; border-top-style: solid; display: inline-block; }
  .swatch.dashed { border-top-style: dashed; }
  .chart-wrap { background: #ffffff; border: 1px solid #E3E3E3; border-radius: 14px; padding: 18px 16px 8px; position: relative; }
  .chart-svg-wrap { position: relative; }
  .axis-labels { display: flex; justify-content: space-between; font-size: 10.5px; color: #9A9A9A; margin-top: 6px; }
  .crosshair-tip {
    position: absolute; top: 6px; background: #0B0B0D; color: #ffffff; font-size: 11.5px;
    padding: 6px 10px; border-radius: 8px; white-space: nowrap; pointer-events: none;
    opacity: 0; transition: opacity 0.1s; transform: translateX(-50%);
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid #EDEDED; color: #3D3D3D; }
  th { color: #9A9A9A; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  td.n { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; color: #121212; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 640px) { .two-col { grid-template-columns: 1fr; } }
  .panel { background: #ffffff; border: 1px solid #E3E3E3; border-radius: 14px; overflow: hidden; }
  .panel h2 { padding: 14px 14px 0; font-size: 16px; }
  .panel h2 span { color: #9A9A9A; font-weight: 400; }
  .empty { color: #9A9A9A; font-size: 13px; padding: 20px; text-align: center; }
  .funnel-row { display: flex; align-items: center; gap: 14px; }
  .funnel-label { width: 132px; flex: none; font-size: 13px; color: #6A6A6A; }
  .funnel-track { flex: 1; background: #FAFAFA; border-radius: 8px; height: 34px; position: relative; overflow: hidden; }
  .funnel-fill { height: 100%; background: #0B0B0D; border-radius: 8px; display: flex; align-items: center; justify-content: flex-end; padding-right: 10px; min-width: 46px; transition: width 0.3s ease; }
  .funnel-fill span { color: #ffffff; font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .funnel-conv { width: 64px; flex: none; text-align: right; font-size: 12.5px; color: #9A9A9A; font-variant-numeric: tabular-nums; }
  footer { max-width: 720px; margin: 40px auto 0; padding: 24px 24px 40px; border-top: 1px solid #EDEDED; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  footer a { text-decoration: none; }
</style>
</head>
<body>
<div class="wrap">

  <header style="max-width: 720px; margin: 0 auto; padding: 32px 24px 0; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;">
    <a href="/" aria-label="Comprsly home" style="display: inline-flex; align-items: center; gap: 10px; text-decoration: none; color: #121212; padding: 10px 4px; margin: -10px -4px;">
      <img src="/privacy/assets/b07c624a68.png" alt="Comprsly" style="width: 22px; height: auto; filter: invert(1); flex-shrink: 0;">
      <span style="font-size: 17px; font-weight: 600; letter-spacing: -0.01em;">Comprsly</span>
    </a>
    <span style="color: #C9C9C9;">/</span>
    <span style="font-size: 15px; color: #6A6A6A;">Analytics</span>
  </header>

  <main>
    <h1>Analytics</h1>
    <p class="sub" id="updated">Loading…<a href="/stats/logout">Sign out</a><button onclick="load()">Refresh</button></p>

    <div class="cards" id="cards"></div>

    <section>
      <h2>Last 30 days</h2>
      <p class="hint">Page visits vs. Download-button clicks, by day.</p>
      <div class="legend">
        <span><i class="swatch" style="border-top-color:#0B0B0D"></i>Page views</span>
        <span><i class="swatch dashed" style="border-top-color:#6A6A6A"></i>Download clicks</span>
      </div>
      <div class="chart-wrap">
        <div class="chart-svg-wrap" id="chartWrap">
          <svg id="chartSvg" viewBox="0 0 600 150" preserveAspectRatio="none" style="width:100%; height:150px; display:block; overflow:visible;"></svg>
          <div class="crosshair-tip" id="tip"></div>
        </div>
        <div class="axis-labels" id="axisLabels"></div>
      </div>
    </section>

    <section>
      <h2>Microsoft Store installs</h2>
      <p class="hint">Real confirmed installs, from Microsoft's own Store Analytics API, not website clicks.</p>
      <div class="cards" id="storeCards"></div>
      <div class="chart-wrap">
        <div class="chart-svg-wrap" id="storeChartWrap">
          <svg id="storeChartSvg" viewBox="0 0 600 150" preserveAspectRatio="none" style="width:100%; height:150px; display:block; overflow:visible;"></svg>
          <div class="crosshair-tip" id="storeTip"></div>
        </div>
        <div class="axis-labels" id="storeAxisLabels"></div>
      </div>
    </section>

    <section>
      <h2>Conversion funnel <span style="color:#9A9A9A; font-weight:400; font-size:16px;">(30d)</span></h2>
      <p class="hint">Website visit → Download click → confirmed Microsoft Store install. Aggregate totals over the same window, not a per-person trace, the Store doesn't tell us which specific install came from which website visit.</p>
      <div class="chart-wrap" style="padding: 20px 20px 16px;">
        <div id="funnel" style="display:flex; flex-direction:column; gap:14px;"></div>
      </div>
    </section>

    <section>
      <h2>App usage after install <span style="color:#9A9A9A; font-weight:400; font-size:16px;">(retention)</span></h2>
      <p class="hint">This is the real retention signal: not how many people installed Comprsly, but how many actually opened and used it afterward, and for how long. From Microsoft's own Store telemetry, not anything Comprsly's own code collects.</p>
      <div class="cards" id="usageCards"></div>
    </section>

    <section>
      <h2>Ratings <span style="color:#9A9A9A; font-weight:400; font-size:16px;">(Microsoft Store)</span></h2>
      <p class="hint">Real star ratings customers left on the Store listing.</p>
      <div class="chart-wrap" style="padding: 20px 20px 16px;">
        <div id="ratings"></div>
      </div>
    </section>

    <section>
      <h2>Reviews <span style="color:#9A9A9A; font-weight:400; font-size:16px;">(Microsoft Store, most recent)</span></h2>
      <p class="hint">The actual written reviews customers left, pulled straight from the Store.</p>
      <div id="reviews" style="display:flex; flex-direction:column; gap:10px;"></div>
    </section>

    <section>
      <h2>Crashes &amp; errors <span style="color:#9A9A9A; font-weight:400; font-size:16px;">(30d)</span></h2>
      <p class="hint">Real crash and error reports from Windows itself, the same system that shows you an app "stopped working" dialog. This is separate from Comprsly's own code, so it doesn't conflict with the "no telemetry" promise, it's Microsoft watching, not Comprsly.</p>
      <div class="chart-wrap" style="padding: 16px 20px;">
        <div id="failures"></div>
      </div>
    </section>

    <div class="two-col">
      <section class="panel">
        <h2>Top referrers <span>(30d)</span></h2>
        <table id="referrers"></table>
      </section>
      <section class="panel">
        <h2>Top countries <span>(30d)</span></h2>
        <table id="countries"></table>
      </section>
    </div>

    <section class="panel" style="padding: 16px 20px 20px;">
      <h2 style="padding:0;">Highlights</h2>
      <p class="hint" style="margin: -4px 0 12px;">Auto-generated from real visits and clicks, recalculated every refresh.</p>
      <ul id="highlights" style="margin: 0; padding-left: 18px; font-size: 13.5px; color: #3D3D3D; line-height: 1.85;"></ul>
    </section>
  </main>

  <footer>
    <a href="/" aria-label="Comprsly home" style="display: inline-flex; align-items: center; gap: 10px; color: #9A9A9A; padding: 10px 4px; margin: -10px -4px;">
      <img src="/privacy/assets/b07c624a68.png" alt="" style="width: 15px; height: auto; filter: invert(1);">
      <span style="font-size: 13px; color: inherit;">Comprsly Analytics</span>
    </a>
    <a href="/" style="font-size: 13px; color: #6A6A6A; border-bottom: 1px solid #E3E3E3; padding-block: 12px;">Back to site</a>
  </footer>
</div>
<script>
function fmt(n) { return n.toLocaleString(); }

function fmtSeconds(s) {
  if (s === null || s === undefined) return "—";
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60), rem = s % 60;
  return m + "m " + rem + "s";
}

function renderCards(t, avgSessionSeconds) {
  const el = document.getElementById("cards");
  const rate = (dl, pv) => (pv > 0 ? ((dl / pv) * 100).toFixed(1) + "%" : "—");
  el.innerHTML = \`
    <div class="card pageviews">
      <div class="label">Page views</div>
      <div class="row"><span>Last 24h</span><span class="n">\${fmt(t.pageviews.last24h)}</span></div>
      <div class="row"><span>Last 7d</span><span class="n">\${fmt(t.pageviews.last7d)}</span></div>
      <div class="row"><span>Last 30d</span><span class="n">\${fmt(t.pageviews.last30d)}</span></div>
      <div class="row"><span>All time</span><span class="n">\${fmt(t.pageviews.allTime)}</span></div>
    </div>
    <div class="card downloads">
      <div class="label">Download clicks</div>
      <div class="row"><span>Last 24h</span><span class="n">\${fmt(t.downloadClicks.last24h)}</span></div>
      <div class="row"><span>Last 7d</span><span class="n">\${fmt(t.downloadClicks.last7d)}</span></div>
      <div class="row"><span>Last 30d</span><span class="n">\${fmt(t.downloadClicks.last30d)}</span></div>
      <div class="row"><span>All time</span><span class="n">\${fmt(t.downloadClicks.allTime)}</span></div>
    </div>
    <div class="card">
      <div class="label">Click rate (downloads ÷ views)</div>
      <div class="row"><span>Last 7d</span><span class="n">\${rate(t.downloadClicks.last7d, t.pageviews.last7d)}</span></div>
      <div class="row"><span>Last 30d</span><span class="n">\${rate(t.downloadClicks.last30d, t.pageviews.last30d)}</span></div>
      <div class="row"><span>All time</span><span class="n">\${rate(t.downloadClicks.allTime, t.pageviews.allTime)}</span></div>
    </div>
    <div class="card">
      <div class="label">Avg. time on site <span style="font-weight:400;color:#9A9A9A;">(30d)</span></div>
      <div class="row"><span>Per visit</span><span class="n">\${fmtSeconds(avgSessionSeconds)}</span></div>
      <div class="row" style="color:#9A9A9A; font-size:12px;">How long someone stays on the page before leaving, on average.</div>
    </div>
  \`;
}

let currentDaily = [];

function renderChart(daily) {
  currentDaily = daily;
  const svg = document.getElementById("chartSvg");
  const axis = document.getElementById("axisLabels");
  const max = Math.max(1, ...daily.map(d => Math.max(d.pageviews, d.downloadClicks)));
  const n = daily.length;
  const stepX = 600 / (n - 1);
  const toY = v => 148 - (v / max) * 138;

  const pvPts = daily.map((d, i) => [i * stepX, toY(d.pageviews)]);
  const dlPts = daily.map((d, i) => [i * stepX, toY(d.downloadClicks)]);
  const pathOf = pts => "M" + pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L");

  let svgHtml = "";
  [0, 0.5, 1].forEach(f => {
    const y = 10 + f * 138;
    svgHtml += \`<line x1="0" y1="\${y}" x2="600" y2="\${y}" stroke="#EDEDED" stroke-width="1"/>\`;
  });
  svgHtml += \`<path d="\${pathOf(pvPts)}" fill="none" stroke="#0B0B0D" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>\`;
  svgHtml += \`<path d="\${pathOf(dlPts)}" fill="none" stroke="#6A6A6A" stroke-width="2" stroke-dasharray="6,4" stroke-linejoin="round" stroke-linecap="round"/>\`;
  svgHtml += \`<line id="crosshairLine" x1="0" y1="0" x2="0" y2="150" stroke="#C9C9C9" stroke-width="1" style="opacity:0;"/>\`;
  svgHtml += \`<circle id="dotPv" r="3.5" fill="#0B0B0D" style="opacity:0;"/>\`;
  svgHtml += \`<circle id="dotDl" r="3.5" fill="#6A6A6A" style="opacity:0;"/>\`;
  svg.innerHTML = svgHtml;

  axis.innerHTML = daily.map((d, i) => (i % 5 === 0 ? \`<span>\${d.date.slice(5)}</span>\` : "<span></span>")).join("");

  const wrap = document.getElementById("chartWrap");
  const tip = document.getElementById("tip");
  wrap.onmousemove = e => {
    const rect = svg.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * 600;
    const i = Math.max(0, Math.min(n - 1, Math.round(relX / stepX)));
    const d = currentDaily[i];
    const x = pvPts[i][0], yPv = pvPts[i][1], yDl = dlPts[i][1];
    document.getElementById("crosshairLine").setAttribute("x1", x);
    document.getElementById("crosshairLine").setAttribute("x2", x);
    document.getElementById("crosshairLine").style.opacity = 1;
    const dotPv = document.getElementById("dotPv");
    dotPv.setAttribute("cx", x); dotPv.setAttribute("cy", yPv); dotPv.style.opacity = 1;
    const dotDl = document.getElementById("dotDl");
    dotDl.setAttribute("cx", x); dotDl.setAttribute("cy", yDl); dotDl.style.opacity = 1;
    tip.style.left = ((x / 600) * rect.width) + "px";
    tip.style.opacity = 1;
    tip.textContent = d.date + " — " + d.pageviews + " views, " + d.downloadClicks + " clicks";
  };
  wrap.onmouseleave = () => {
    document.getElementById("crosshairLine").style.opacity = 0;
    document.getElementById("dotPv").style.opacity = 0;
    document.getElementById("dotDl").style.opacity = 0;
    tip.style.opacity = 0;
  };
}

function renderStoreCards(storeInstalls) {
  const el = document.getElementById("storeCards");
  if (!storeInstalls) {
    el.innerHTML = '<div class="card"><div class="empty" style="padding:8px 0;">Store data not available right now.</div></div>';
    return;
  }
  const t = storeInstalls.totals;
  el.innerHTML = \`
    <div class="card pageviews">
      <div class="label">Installs</div>
      <div class="row"><span>Last 24h</span><span class="n">\${fmt(t.last24h)}</span></div>
      <div class="row"><span>Last 7d</span><span class="n">\${fmt(t.last7d)}</span></div>
      <div class="row"><span>Last 30d</span><span class="n">\${fmt(t.last30d)}</span></div>
      <div class="row"><span>All time</span><span class="n">\${fmt(t.allTime)}</span></div>
    </div>
  \`;
}

function renderStoreChart(daily) {
  const svg = document.getElementById("storeChartSvg");
  const axis = document.getElementById("storeAxisLabels");
  if (!daily || !daily.length) {
    svg.innerHTML = "";
    axis.innerHTML = "";
    return;
  }
  const max = Math.max(1, ...daily.map(d => d.installs));
  const n = daily.length;
  const stepX = 600 / (n - 1);
  const toY = v => 148 - (v / max) * 138;
  const pts = daily.map((d, i) => [i * stepX, toY(d.installs)]);
  const pathOf = ptsArr => "M" + ptsArr.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L");

  let svgHtml = "";
  [0, 0.5, 1].forEach(f => {
    const y = 10 + f * 138;
    svgHtml += \`<line x1="0" y1="\${y}" x2="600" y2="\${y}" stroke="#EDEDED" stroke-width="1"/>\`;
  });
  svgHtml += \`<path d="\${pathOf(pts)}" fill="none" stroke="#0B0B0D" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>\`;
  svgHtml += \`<line id="storeCrosshairLine" x1="0" y1="0" x2="0" y2="150" stroke="#C9C9C9" stroke-width="1" style="opacity:0;"/>\`;
  svgHtml += \`<circle id="storeDot" r="3.5" fill="#0B0B0D" style="opacity:0;"/>\`;
  svg.innerHTML = svgHtml;

  axis.innerHTML = daily.map((d, i) => (i % 5 === 0 ? \`<span>\${d.date.slice(5)}</span>\` : "<span></span>")).join("");

  const wrap = document.getElementById("storeChartWrap");
  const tip = document.getElementById("storeTip");
  wrap.onmousemove = e => {
    const rect = svg.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * 600;
    const i = Math.max(0, Math.min(n - 1, Math.round(relX / stepX)));
    const d = daily[i];
    const x = pts[i][0], y = pts[i][1];
    document.getElementById("storeCrosshairLine").setAttribute("x1", x);
    document.getElementById("storeCrosshairLine").setAttribute("x2", x);
    document.getElementById("storeCrosshairLine").style.opacity = 1;
    const dot = document.getElementById("storeDot");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.style.opacity = 1;
    tip.style.left = ((x / 600) * rect.width) + "px";
    tip.style.opacity = 1;
    tip.textContent = d.date + " — " + d.installs + " installs";
  };
  wrap.onmouseleave = () => {
    document.getElementById("storeCrosshairLine").style.opacity = 0;
    document.getElementById("storeDot").style.opacity = 0;
    tip.style.opacity = 0;
  };
}

function renderFunnel(data) {
  const el = document.getElementById("funnel");
  const views = data.totals.pageviews.last30d;
  const clicks = data.totals.downloadClicks.last30d;
  const installs = data.storeInstalls ? data.storeInstalls.totals.last30d : null;

  const stages = [
    { label: "Website visits", value: views },
    { label: "Download clicks", value: clicks },
    { label: "Store installs", value: installs }
  ];

  if (installs === null) {
    el.innerHTML = '<div class="empty">Store install data not available right now.</div>';
    return;
  }

  const max = Math.max(1, views);
  el.innerHTML = stages.map((s, i) => {
    const pct = max > 0 ? Math.max((s.value / max) * 100, s.value > 0 ? 4 : 0) : 0;
    const convHtml = i === 0
      ? ""
      : \`<div class="funnel-conv">\${stages[i - 1].value > 0 ? ((s.value / stages[i - 1].value) * 100).toFixed(1) + "%" : "—"}</div>\`;
    return \`<div class="funnel-row">
      <div class="funnel-label">\${s.label}</div>
      <div class="funnel-track"><div class="funnel-fill" style="width:\${pct}%"><span>\${fmt(s.value)}</span></div></div>
      \${convHtml || '<div class="funnel-conv"></div>'}
    </div>\`;
  }).join("");
}

function renderUsage(storeUsage) {
  const el = document.getElementById("usageCards");
  if (!storeUsage) {
    el.innerHTML = '<div class="card"><div class="empty" style="padding:8px 0;">Usage data not available right now.</div></div>';
    return;
  }
  el.innerHTML = \`
    <div class="card">
      <div class="label">Active devices</div>
      <div class="row"><span>Last 7d</span><span class="n">\${fmt(storeUsage.activeDevicesLast7d)}</span></div>
      <div class="row"><span>Last 30d</span><span class="n">\${fmt(storeUsage.activeDevicesLast30d)}</span></div>
      <div class="row" style="color:#9A9A9A; font-size:12px;">Devices that actually opened the app, not just installed it.</div>
    </div>
    <div class="card">
      <div class="label">Avg. session length</div>
      <div class="row"><span>Per open</span><span class="n">\${storeUsage.avgSessionMinutes > 0 ? storeUsage.avgSessionMinutes + " min" : "—"}</span></div>
      <div class="row" style="color:#9A9A9A; font-size:12px;">How long people keep the app running each time they open it.</div>
    </div>
  \`;
}

function renderRatings(storeRatings) {
  const el = document.getElementById("ratings");
  if (!storeRatings || storeRatings.count === 0) {
    el.innerHTML = '<div class="empty">No ratings yet. This will fill in once real customers start rating Comprsly in the Store.</div>';
    return;
  }
  const rows = [
    { label: "5 stars", value: storeRatings.fiveStars },
    { label: "4 stars", value: storeRatings.fourStars },
    { label: "3 stars", value: storeRatings.threeStars },
    { label: "2 stars", value: storeRatings.twoStars },
    { label: "1 star", value: storeRatings.oneStar }
  ];
  const max = Math.max(1, ...rows.map(r => r.value));
  const bars = rows.map(r => {
    const pct = Math.max((r.value / max) * 100, r.value > 0 ? 4 : 0);
    return \`<div class="funnel-row">
      <div class="funnel-label" style="width:64px;">\${r.label}</div>
      <div class="funnel-track"><div class="funnel-fill" style="width:\${pct}%"><span>\${fmt(r.value)}</span></div></div>
    </div>\`;
  }).join("");
  el.innerHTML = \`<div style="margin-bottom:14px; font-size:14px; color:#121212;"><strong style="font-size:22px;">\${storeRatings.average}</strong> average out of 5, from \${fmt(storeRatings.count)} rating\${storeRatings.count === 1 ? "" : "s"}</div>\` +
    '<div style="display:flex; flex-direction:column; gap:10px;">' + bars + '</div>';
}

function renderReviews(storeReviews) {
  const el = document.getElementById("reviews");
  if (!storeReviews || !storeReviews.length) {
    el.innerHTML = '<div class="empty">No written reviews yet.</div>';
    return;
  }
  el.innerHTML = storeReviews.map(r => {
    const stars = "★".repeat(r.rating || 0) + "☆".repeat(5 - (r.rating || 0));
    return \`<div style="border:1px solid #E3E3E3; border-radius:12px; padding:14px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:4px;">
        <span style="color:#0B0B0D; letter-spacing:1px;">\${stars}</span>
        <span style="font-size:11.5px; color:#9A9A9A;">\${(r.date || "").slice(0, 10)}\${r.market ? " · " + (COUNTRY_NAMES[r.market] || r.market) : ""}</span>
      </div>
      \${r.title ? \`<div style="font-weight:600; font-size:13.5px; margin-bottom:2px;">\${r.title}</div>\` : ""}
      <div style="font-size:13.5px; color:#3D3D3D; line-height:1.55;">\${r.text || "<em style=\\'color:#9A9A9A;\\'>No written comment</em>"}</div>
    </div>\`;
  }).join("");
}

function renderFailures(storeFailures) {
  const el = document.getElementById("failures");
  if (!storeFailures || storeFailures.top.length === 0) {
    el.innerHTML = '<div class="empty">No crashes or errors reported in the last 30 days.</div>';
    return;
  }
  const rows = storeFailures.top.map(f =>
    \`<tr><td>\${f.eventType}</td><td style="color:#3D3D3D;">\${f.name.length > 70 ? f.name.slice(0, 70) + "…" : f.name}</td><td class="n">\${f.count}</td></tr>\`
  ).join("");
  el.innerHTML = \`<p style="font-size:13.5px; color:#3D3D3D; margin:0 0 12px;"><strong>\${fmt(storeFailures.totalDevicesAffected)}</strong> devices affected in total.</p>
    <table><tr><th>Type</th><th>Failure</th><th style="text-align:right;">Devices</th></tr>\${rows}</table>\`;
}

const COUNTRY_NAMES = {
  AF:"Afghanistan",AX:"Åland Islands",AL:"Albania",DZ:"Algeria",AS:"American Samoa",AD:"Andorra",AO:"Angola",AI:"Anguilla",AQ:"Antarctica",AG:"Antigua and Barbuda",AR:"Argentina",AM:"Armenia",AW:"Aruba",AU:"Australia",AT:"Austria",AZ:"Azerbaijan",BS:"Bahamas",BH:"Bahrain",BD:"Bangladesh",BB:"Barbados",BY:"Belarus",BE:"Belgium",BZ:"Belize",BJ:"Benin",BM:"Bermuda",BT:"Bhutan",BO:"Bolivia",BA:"Bosnia and Herzegovina",BW:"Botswana",BR:"Brazil",BN:"Brunei",BG:"Bulgaria",BF:"Burkina Faso",BI:"Burundi",KH:"Cambodia",CM:"Cameroon",CA:"Canada",CV:"Cabo Verde",KY:"Cayman Islands",CF:"Central African Republic",TD:"Chad",CL:"Chile",CN:"China",CO:"Colombia",KM:"Comoros",CG:"Congo",CD:"DR Congo",CR:"Costa Rica",CI:"Côte d'Ivoire",HR:"Croatia",CU:"Cuba",CW:"Curaçao",CY:"Cyprus",CZ:"Czechia",DK:"Denmark",DJ:"Djibouti",DM:"Dominica",DO:"Dominican Republic",EC:"Ecuador",EG:"Egypt",SV:"El Salvador",GQ:"Equatorial Guinea",ER:"Eritrea",EE:"Estonia",SZ:"Eswatini",ET:"Ethiopia",FJ:"Fiji",FI:"Finland",FR:"France",GF:"French Guiana",PF:"French Polynesia",GA:"Gabon",GM:"Gambia",GE:"Georgia",DE:"Germany",GH:"Ghana",GI:"Gibraltar",GR:"Greece",GL:"Greenland",GD:"Grenada",GP:"Guadeloupe",GU:"Guam",GT:"Guatemala",GG:"Guernsey",GN:"Guinea",GW:"Guinea-Bissau",GY:"Guyana",HT:"Haiti",HN:"Honduras",HK:"Hong Kong",HU:"Hungary",IS:"Iceland",IN:"India",ID:"Indonesia",IR:"Iran",IQ:"Iraq",IE:"Ireland",IM:"Isle of Man",IL:"Israel",IT:"Italy",JM:"Jamaica",JP:"Japan",JE:"Jersey",JO:"Jordan",KZ:"Kazakhstan",KE:"Kenya",KI:"Kiribati",KP:"North Korea",KR:"South Korea",KW:"Kuwait",KG:"Kyrgyzstan",LA:"Laos",LV:"Latvia",LB:"Lebanon",LS:"Lesotho",LR:"Liberia",LY:"Libya",LI:"Liechtenstein",LT:"Lithuania",LU:"Luxembourg",MO:"Macao",MG:"Madagascar",MW:"Malawi",MY:"Malaysia",MV:"Maldives",ML:"Mali",MT:"Malta",MH:"Marshall Islands",MQ:"Martinique",MR:"Mauritania",MU:"Mauritius",MX:"Mexico",FM:"Micronesia",MD:"Moldova",MC:"Monaco",MN:"Mongolia",ME:"Montenegro",MS:"Montserrat",MA:"Morocco",MZ:"Mozambique",MM:"Myanmar",NA:"Namibia",NR:"Nauru",NP:"Nepal",NL:"Netherlands",NC:"New Caledonia",NZ:"New Zealand",NI:"Nicaragua",NE:"Niger",NG:"Nigeria",NU:"Niue",MK:"North Macedonia",NO:"Norway",OM:"Oman",PK:"Pakistan",PW:"Palau",PS:"Palestine",PA:"Panama",PG:"Papua New Guinea",PY:"Paraguay",PE:"Peru",PH:"Philippines",PL:"Poland",PT:"Portugal",PR:"Puerto Rico",QA:"Qatar",RE:"Réunion",RO:"Romania",RU:"Russia",RW:"Rwanda",KN:"Saint Kitts and Nevis",LC:"Saint Lucia",VC:"Saint Vincent and the Grenadines",WS:"Samoa",SM:"San Marino",SA:"Saudi Arabia",SN:"Senegal",RS:"Serbia",SC:"Seychelles",SL:"Sierra Leone",SG:"Singapore",SK:"Slovakia",SI:"Slovenia",SB:"Solomon Islands",SO:"Somalia",ZA:"South Africa",SS:"South Sudan",ES:"Spain",LK:"Sri Lanka",SD:"Sudan",SR:"Suriname",SE:"Sweden",CH:"Switzerland",SY:"Syria",TW:"Taiwan",TJ:"Tajikistan",TZ:"Tanzania",TH:"Thailand",TL:"Timor-Leste",TG:"Togo",TO:"Tonga",TT:"Trinidad and Tobago",TN:"Tunisia",TR:"Türkiye",TM:"Turkmenistan",TV:"Tuvalu",UG:"Uganda",UA:"Ukraine",AE:"United Arab Emirates",GB:"United Kingdom",US:"United States",UY:"Uruguay",UZ:"Uzbekistan",VU:"Vanuatu",VA:"Vatican City",VE:"Venezuela",VN:"Vietnam",VG:"British Virgin Islands",VI:"U.S. Virgin Islands",YE:"Yemen",ZM:"Zambia",ZW:"Zimbabwe",XX:"Unknown"
};

function renderTable(el, rows, labelKey) {
  if (!rows.length) {
    el.innerHTML = '<tr><td class="empty">No data yet</td></tr>';
    return;
  }
  const labelOf = r => {
    const raw = r[labelKey] || "unknown";
    if (labelKey === "country") {
      const name = COUNTRY_NAMES[raw];
      return name ? \`\${name} <span style="color:#9A9A9A;">(\${raw})</span>\` : raw;
    }
    return raw;
  };
  el.innerHTML =
    "<tr><th>" + (labelKey === "referrer" ? "Referrer" : "Country") + "</th><th style='text-align:right'>Views</th></tr>" +
    rows.map(r => \`<tr><td>\${labelOf(r)}</td><td class="n">\${fmt(r.count)}</td></tr>\`).join("");
}

function pctChange(curr, prev) {
  if (prev === 0) return curr === 0 ? 0 : null;
  return ((curr - prev) / prev) * 100;
}

function renderHighlights(data) {
  const el = document.getElementById("highlights");
  const daily = data.daily;
  const last7 = daily.slice(-7);
  const prev7 = daily.slice(-14, -7);
  const sum = (arr, key) => arr.reduce((a, d) => a + d[key], 0);
  const pv7 = sum(last7, "pageviews"), pvPrev7 = sum(prev7, "pageviews");
  const dl7 = sum(last7, "downloadClicks"), dlPrev7 = sum(prev7, "downloadClicks");
  const bullets = [];

  if (pv7 === 0 && pvPrev7 === 0) {
    bullets.push("No page views yet in the last two weeks.");
  } else if (pvPrev7 === 0) {
    bullets.push(\`Page views this week: \${pv7}, up from 0 the week before.\`);
  } else {
    const chg = pctChange(pv7, pvPrev7);
    bullets.push(\`Page views this week: \${pv7}, \${chg >= 0 ? "up" : "down"} \${Math.abs(chg).toFixed(0)}% from the week before (\${pvPrev7}).\`);
  }

  if (dl7 === 0 && dlPrev7 === 0) {
    bullets.push("No download clicks yet in the last two weeks.");
  } else if (dlPrev7 === 0) {
    bullets.push(\`Download clicks this week: \${dl7}, up from 0 the week before.\`);
  } else {
    const chg = pctChange(dl7, dlPrev7);
    bullets.push(\`Download clicks this week: \${dl7}, \${chg >= 0 ? "up" : "down"} \${Math.abs(chg).toFixed(0)}% from the week before (\${dlPrev7}).\`);
  }

  const refTotal = data.topReferrers.reduce((a, r) => a + r.count, 0);
  if (data.topReferrers.length && refTotal > 0) {
    const top = data.topReferrers[0];
    const pct = ((top.count / refTotal) * 100).toFixed(0);
    const label = top.referrer === "direct" ? "direct traffic (no referrer)" : top.referrer;
    bullets.push(\`Most visits come from \${label}, \${pct}% of the last 30 days.\`);
  }

  const countryTotal = data.topCountries.reduce((a, r) => a + r.count, 0);
  if (data.topCountries.length && countryTotal > 0) {
    const top = data.topCountries[0];
    const pct = ((top.count / countryTotal) * 100).toFixed(0);
    bullets.push(\`Most visitors are in \${COUNTRY_NAMES[top.country] || top.country}, \${pct}% of the last 30 days.\`);
  }

  const pv30 = data.totals.pageviews.last30d, dl30 = data.totals.downloadClicks.last30d;
  if (pv30 > 0) {
    bullets.push(\`\${((dl30 / pv30) * 100).toFixed(1)}% of visitors in the last 30 days clicked Download.\`);
  }

  el.innerHTML = bullets.length
    ? bullets.map(b => \`<li>\${b}</li>\`).join("")
    : '<li style="color:#9A9A9A;">Not enough data yet.</li>';
}

async function load() {
  document.getElementById("updated").firstChild.textContent = "Loading…";
  try {
    const res = await fetch("/api/stats" + location.search, { cache: "no-store" });
    if (!res.ok) throw new Error("unauthorized or request failed");
    const data = await res.json();
    renderCards(data.totals, data.avgSessionSeconds);
    renderChart(data.daily);
    renderStoreCards(data.storeInstalls);
    renderStoreChart(data.storeInstalls ? data.storeInstalls.daily : null);
    renderFunnel(data);
    renderUsage(data.storeUsage);
    renderRatings(data.storeRatings);
    renderReviews(data.storeReviews);
    renderFailures(data.storeFailures);
    renderTable(document.getElementById("referrers"), data.topReferrers, "referrer");
    renderTable(document.getElementById("countries"), data.topCountries, "country");
    renderHighlights(data);
    document.getElementById("updated").firstChild.textContent =
      "Updated " + new Date(data.generatedAt).toLocaleTimeString() + " · auto-refreshes every 60s";
  } catch (e) {
    document.getElementById("updated").firstChild.textContent = "Couldn't load data, try signing in again";
  }
}

load();
setInterval(load, 60000);
</script>
</body>
</html>`;
