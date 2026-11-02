/* Cosmetic Google AI Mode suppression for the controlled NERDs Firefox.
 * The webRequest guard remains the navigation control; Google can change
 * button markup, so CSS alone must never be treated as enforcement.
 * Do not inspect page text or collect search queries here.
 */
"use strict";

const style = document.createElement("style");
style.id = "nerds-google-web-only-ui";
style.textContent = [
  'a[href="/ai"]',
  'a[href^="/ai?"]',
  'a[href^="/aimode"]',
  'a[href*="/search?udm=50"]',
  'a[href*="&udm=50"]',
  'a[href*="?udm=50"]'
].join(",") + "{display:none!important}";
(document.documentElement || document.head)?.appendChild(style);
