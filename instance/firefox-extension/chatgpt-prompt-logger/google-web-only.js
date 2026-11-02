/* NERDs Pilot 1: conventional Google Web results only.
 * URL rewrites do not collect query text. The existing browser observation
 * module still handles task-attributed search and navigation recording.
 */
"use strict";

function nerdsGoogleWebRedirect(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch (_) { return null; }
  if (!["https:", "http:"].includes(url.protocol)) return null;
  if (!["google.com", "www.google.com"].includes(url.hostname.toLowerCase())) return null;

  const path = url.pathname.replace(/\/+$/, "") || "/";
  const q = url.searchParams.get("q");
  const validQuery = typeof q === "string" && q.trim().length > 0;

  // Known Google AI Mode paths and filters. New Google surfaces must be
  // evaluated separately; this is not a universal Google AI shutdown.
  const aiPage = /^\/(?:ai|aimode)(?:\/|$)/i.test(url.pathname);
  const aiParam = url.searchParams.get("udm") === "50" ||
    url.searchParams.get("mode")?.toLowerCase() === "ai" ||
    url.searchParams.get("tbm")?.toLowerCase() === "ai";

  if (aiPage || (aiParam && path !== "/search")) {
    return validQuery
      ? "https://www.google.com/search?q=" + encodeURIComponent(q) + "&udm=14"
      : "https://www.google.com/";
  }

  // Handle Firefox address-bar searches, Google's own search form,
  // and manually entered /search URLs.
  if (path === "/search" || (path === "/" && validQuery)) {
    if (!validQuery) return aiParam ? "https://www.google.com/" : null;
    const alreadyWeb = path === "/search" &&
      url.searchParams.get("udm") === "14" &&
      !url.searchParams.has("tbm") &&
      !url.searchParams.has("mode") &&
      !url.searchParams.has("aep");
    if (alreadyWeb) return null;

    const params = new URLSearchParams();
    params.set("q", q);
    params.set("udm", "14");
    for (const name of ["hl", "start", "safe"]) {
      const value = url.searchParams.get(name);
      if (value) params.set(name, value.slice(0, 80));
    }
    return "https://www.google.com/search?" + params.toString();
  }
  return null;
}

if (typeof browser !== "undefined" && browser.webRequest?.onBeforeRequest) {
  browser.webRequest.onBeforeRequest.addListener(
    (details) => {
      if (details.type !== "main_frame") return {};
      const redirectUrl = nerdsGoogleWebRedirect(details.url);
      if (redirectUrl && redirectUrl !== details.url) {
        // Never log the search text or the URL in extension debug output.
        console.log("[NERDs Search] conventional Web results enforced");
        return { redirectUrl };
      }
      return {};
    },
    {
      urls: ["*://google.com/*", "*://www.google.com/*"],
      types: ["main_frame"]
    },
    ["blocking"]
  );
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { nerdsGoogleWebRedirect };
}
