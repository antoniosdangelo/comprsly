import PostalMime from "postal-mime";
import { handleStatsApi, handleStatsPage, handleStatsLogin, handleStatsLogout } from "./stats.js";
import { refreshStoreCache } from "./store-analytics.js";

const FORWARD_TO = "antoniosdangeloo@gmail.com";
const SEND_FROM = "Comprsly Contact <contact@comprsly.com>";

// Antonio's explicit call, 2026-07-29: link straight to the Store listing now,
// even though it currently 404s (ProductNotFound) since certification hasn't
// passed yet. Accepted knowingly rather than maintain any live-checking logic —
// certification is expected soon, and the redirect needs zero further action
// once it does.
const STORE_URL = "https://apps.microsoft.com/detail/9N8W5HPJ4DHV";

// Coarse UA filter so bot/crawler traffic doesn't pollute the funnel numbers.
// Not trying to be a real bot-detection system, just cheap noise reduction.
const BOT_UA = /bot|crawl|spider|slurp|facebookexternalhit|headlesschrome|curl|wget|python-requests/i;

const TRACKED_PATHS = new Set(["/", "/privacy", "/privacy/"]);

function refererHost(request) {
  const referer = request.headers.get("Referer");
  if (!referer) return "direct";
  try {
    return new URL(referer).hostname;
  } catch {
    return "direct";
  }
}

// Fire-and-forget via ctx.waitUntil so a slow/failed insert never adds
// latency or breaks the real page response.
function logEvent(env, ctx, { event, path, request, value }) {
  if (!env.ANALYTICS_DB) return;
  const ua = request.headers.get("User-Agent") || "";
  if (BOT_UA.test(ua)) return;
  ctx.waitUntil(
    env.ANALYTICS_DB.prepare(
      "INSERT INTO events (ts, event, path, referrer, country, value) VALUES (?, ?, ?, ?, ?, ?)"
    )
      .bind(Date.now(), event, path, refererHost(request), request.cf?.country || "XX", value ?? null)
      .run()
      .catch((err) => console.error("analytics insert failed:", err))
  );
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/stats") {
      return handleStatsApi(request, env, url);
    }
    if (url.pathname === "/stats") {
      return handleStatsPage(request, env, url);
    }
    if (url.pathname === "/stats/login" && request.method === "POST") {
      return handleStatsLogin(request, env);
    }
    if (url.pathname === "/stats/logout") {
      return handleStatsLogout();
    }
    if (url.pathname === "/api/session-duration" && request.method === "POST") {
      try {
        const body = await request.json();
        // Clamp to 30 minutes — anything beyond that is almost certainly a
        // forgotten background tab, not real engaged time on the page, and
        // would badly skew the average.
        const seconds = Math.max(0, Math.min(1800, Math.round(Number(body.seconds) || 0)));
        if (seconds > 0) {
          logEvent(env, ctx, { event: "session_duration", path: body.path || "/", request, value: seconds });
        }
      } catch {
        // malformed beacon payload — ignore, never worth failing the page over
      }
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/go/store") {
      logEvent(env, ctx, { event: "download_click", path: url.pathname, request });
      return Response.redirect(STORE_URL, 302);
    }
    if (request.method === "GET" && TRACKED_PATHS.has(url.pathname)) {
      logEvent(env, ctx, { event: "pageview", path: url.pathname, request });
    }
    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);
    headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("X-Frame-Options", "SAMEORIGIN");
    headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
    headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers
    });
  },

  async email(message, env, ctx) {
    const email = await PostalMime.parse(message.raw);

    const senderName = email.from?.name || email.from?.address || message.from;
    const senderAddress = email.from?.address || message.from;

    const resendResponse = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        from: SEND_FROM,
        to: [FORWARD_TO],
        reply_to: senderAddress,
        subject: email.subject || "(no subject)",
        text: `From: ${senderName} <${senderAddress}>\n\n${email.text || ""}`,
        html: email.html
          ? `<p><strong>From:</strong> ${senderName} &lt;${senderAddress}&gt;</p><hr>${email.html}`
          : undefined
      })
    });

    if (!resendResponse.ok) {
      const errorBody = await resendResponse.text();
      console.error("Resend send failed:", resendResponse.status, errorBody);
      throw new Error(`Resend API error: ${resendResponse.status}`);
    }
  },

  // Refreshes the Store analytics cache on a schedule (see wrangler.jsonc
  // triggers.crons). Never called from a live page request — /api/stats only
  // ever reads the cache — this is the sole place that talks to the Store API,
  // deliberately, to stay clear of its rate limit.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(refreshStoreCache(env));
  }
};
