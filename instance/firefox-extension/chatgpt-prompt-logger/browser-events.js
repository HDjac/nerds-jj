/* NERDs browser observation v0.8.
 * Top-level navigations only; no page text, cookies, request bodies or headers.
 * Each event is stamped with the active task_run_id BEFORE it is queued.
 * The server must revalidate task/session ownership before inserting events.
 */
"use strict";

const NERDS_BROWSER_ENDPOINT = "http://127.0.0.1:60000/log-browser-event";
const NERDS_CONTEXT_ENDPOINT = "http://127.0.0.1:60000/api/pilot1/browser-context";
const NERDS_QUEUE_KEY = "nerds_browser_events_v1";
const NERDS_DROPPED_KEY = "nerds_browser_dropped_v1";
const NERDS_MAX_QUEUE = 2000;
const NERDS_RETRY_ALARM = "nerds-browser-retry";

function nerdsBrowserSafeNavigation(details, navType) {
  if (!details || details.frameId !== 0 || typeof details.url !== "string") return null;
  let parsed;
  try { parsed = new URL(details.url); } catch (_) { return null; }
  if (!["http:", "https:"].includes(parsed.protocol)) return null;

  const host = parsed.hostname.toLowerCase();
  if (!host || host === "localhost" || host.endsWith(".localhost") ||
      host === "127.0.0.1" || host === "::1" || host.endsWith(".local") ||
      /^10\./.test(host) || /^192\.168\./.test(host) ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return null;

  // Never preserve credentials, fragments, or arbitrary query parameters.
  // Path segments resembling opaque credentials/tokens are redacted.
  let pathname = parsed.pathname.split("/").map(segment => {
    if (/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9-]{15,}$/i.test(segment) ||
        /^[a-z0-9_-]{32,}$/i.test(segment) ||
        segment.length > 120) return "[redacted]";
    return segment;
  }).join("/");
  if (pathname.length > 1500) pathname = pathname.slice(0, 1500);
  const safeUrl = `${parsed.protocol}//${host}${parsed.port ? ":" + parsed.port : ""}${pathname}`;

  let searchEngine = null;
  let query = null;
  if (/^(www\.)?google\.[a-z.]+$/.test(host) && pathname === "/search") {
    searchEngine = "google";
    query = parsed.searchParams.get("q");
  } else if (/^(www\.)?bing\.com$/.test(host) && pathname === "/search") {
    searchEngine = "bing";
    query = parsed.searchParams.get("q");
  } else if (/^(www\.)?duckduckgo\.com$/.test(host) && (pathname === "/" || pathname === "/html/")) {
    searchEngine = "duckduckgo";
    query = parsed.searchParams.get("q");
  }
  query = typeof query === "string" ? query.replace(/\s+/g, " ").trim().slice(0, 1200) : null;
  if (!query) searchEngine = null;

  return {
    event_id: crypto.randomUUID(),
    event_kind: searchEngine ? "search" : "navigation",
    url: safeUrl,
    page_host: host,
    search_engine: searchEngine,
    search_query: query,
    navigation_type: navType === "history" ? "history_state" : "committed",
    transition_type: typeof details.transitionType === "string" ? details.transitionType.slice(0, 40) : "unknown",
    browser_tab_id: Number.isInteger(details.tabId) ? details.tabId : -1,
    client_timestamp: new Date().toISOString()
  };
}

function nerdsBrowserCountDrop(reason) {
  return browser.storage.local.get(NERDS_DROPPED_KEY).then(state => {
    const counters = state[NERDS_DROPPED_KEY] || {};
    counters[reason] = (counters[reason] || 0) + 1;
    return browser.storage.local.set({ [NERDS_DROPPED_KEY]: counters });
  }).catch(() => {});
}

let nerdsQueueLock = Promise.resolve();
function nerdsLocked(action) {
  const next = nerdsQueueLock.then(action, action);
  nerdsQueueLock = next.catch(() => {});
  return next;
}

async function nerdsBrowserCapture(details, navType) {
  const observation = nerdsBrowserSafeNavigation(details, navType);
  if (!observation) return;
  try {
    const response = await fetch(NERDS_CONTEXT_ENDPOINT, { cache: "no-store" });
    if (!response.ok) throw new Error(`task context ${response.status}`);
    const ctx = await response.json();
    if (typeof ctx.task_run_id !== "string" ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(ctx.task_run_id)) {
      throw new Error("invalid task context");
    }
    observation.expected_task_run_id = ctx.task_run_id;
    await nerdsLocked(async () => {
      const state = await browser.storage.local.get(NERDS_QUEUE_KEY);
      const items = state[NERDS_QUEUE_KEY] || [];
      if (items.length >= NERDS_MAX_QUEUE) {
        await nerdsBrowserCountDrop("queue_full");
        return;
      }
      items.push(observation);
      await browser.storage.local.set({ [NERDS_QUEUE_KEY]: items });
    });
    await nerdsBrowserFlush();
  } catch (e) {
    await nerdsBrowserCountDrop("context_unavailable");
    console.warn("[NERDs Browser] observation could not be bound to task", String(e));
  }
}

let nerdsFlushRunning = false;
async function nerdsBrowserFlush() {
  if (nerdsFlushRunning) return;
  nerdsFlushRunning = true;
  try {
    for (let n = 0; n < 100; n++) {
      const event = await nerdsLocked(async () => {
        const state = await browser.storage.local.get(NERDS_QUEUE_KEY);
        return (state[NERDS_QUEUE_KEY] || [])[0] || null;
      });
      if (!event) break;
      let response;
      try {
        response = await fetch(NERDS_BROWSER_ENDPOINT, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(event)
        });
      } catch (err) {
        console.warn("[NERDs Browser] ingest temporarily unavailable", String(err));
        break;
      }
      if (!response.ok && response.status !== 409 && response.status !== 410) {
        console.warn("[NERDs Browser] ingest rejected", response.status);
        break;
      }
      if (!response.ok) await nerdsBrowserCountDrop("stale_task_or_rejected");
      await nerdsLocked(async () => {
        const state = await browser.storage.local.get(NERDS_QUEUE_KEY);
        const queue = state[NERDS_QUEUE_KEY] || [];
        if (queue.length && queue[0].event_id === event.event_id) queue.shift();
        await browser.storage.local.set({ [NERDS_QUEUE_KEY]: queue });
      });
    }
  } catch (err) {
    console.warn("[NERDs Browser] local queue unavailable", String(err));
  } finally {
    nerdsFlushRunning = false;
  }
}

if (typeof browser !== "undefined" && browser.webNavigation) {
  browser.webNavigation.onCommitted.addListener(details => {
    void nerdsBrowserCapture(details, "committed");
  });
  browser.webNavigation.onHistoryStateUpdated.addListener(details => {
    void nerdsBrowserCapture(details, "history");
  });
  browser.alarms.create(NERDS_RETRY_ALARM, { periodInMinutes: 1 });
  browser.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === NERDS_RETRY_ALARM) void nerdsBrowserFlush();
  });
  void nerdsBrowserFlush();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { nerdsBrowserSafeNavigation };
}
