/* In-memory clipboard shared by the participant task sidebar and noVNC.
 * Never import the host OS clipboard, persist plaintext, or log its contents.
 * This is a UI transport, not yet a clipboard-event research logger.
 */
import { recordClipboardActivity } from "./clipboardActivity";

const MAX_INTERNAL_CHARS = 65536;
let currentSource = "unknown";
// This is limited observational evidence, not proof of a remote paste.
// No duplicated clipboard text, history, hash, or URL is stored here.
const OBSERVATION_MAX_AGE_MS = 15000;
let observedVncSource = "unknown";
let observedVncAt = 0;

// Only a recent VNC clipboard notification for a matching source/value may
// allow a text candidate to be sent. Cached Firefox selection fallback,
// Guide/sidebar copies, unknown origins, and stale copies fail closed.
export function getNerdsObservedClipboardText(source, text) {
  if (source !== "internal_cli" && source !== "internal_browser") return undefined;
  if (source !== currentSource || source !== observedVncSource) return undefined;
  if (typeof text !== "string" || !text.length ||
      text !== getNerdsInternalClipboard()) return undefined;
  if (observedVncAt <= 0 || Date.now() - observedVncAt < 0 ||
      Date.now() - observedVncAt > OBSERVATION_MAX_AGE_MS) return undefined;
  return text;
}

const OLD_STORAGE_KEYS = [
  "NERDS_INTERNAL_CLIPBOARD",
  "NERDS_INTERNAL_CLIPBOARD_SOURCE",
  "NERDS_INTERNAL_CLIPBOARD_TS",
];

function clearLegacyPersistentClipboard() {
  try { OLD_STORAGE_KEYS.forEach(key => window.localStorage.removeItem(key)); }
  catch (_) { /* Storage may be blocked; keep the in-memory clipboard working. */ }
}

export function getNerdsInternalClipboard() {
  clearLegacyPersistentClipboard();
  return typeof window.__NERDS_INTERNAL_CLIPBOARD__ === "string"
    ? window.__NERDS_INTERNAL_CLIPBOARD__ : "";
}

export function getNerdsInternalClipboardSource() {
  return currentSource;
}

export function setNerdsInternalClipboard(text, source, options = {}) {
  if (typeof text !== "string" || !text.length) return false;
  clearLegacyPersistentClipboard();
  const value = text.slice(0, MAX_INTERNAL_CHARS);
  window.__NERDS_INTERNAL_CLIPBOARD__ = value;
  const uiCopies = {
    task_description: ["task_sidebar", "copy_button"],
    task_sidebar: ["task_sidebar", "sidebar_keyboard"],
    fuzzing_guide_command: ["fuzzing_guide", "copy_button"],
  };
  const observed = {
    internal_cli: "internal_cli",
    internal_browser: "internal_browser",
    code_editor: "other_internal",
  };
  const uiCopy = uiCopies[source];
  const observedSource = observed[source];
  currentSource = uiCopy ? uiCopy[0] : (observedSource || "unknown");
  if (options.observedFromVnc === true &&
      (currentSource === "internal_cli" || currentSource === "internal_browser")) {
    observedVncSource = currentSource;
    observedVncAt = Date.now();
  } else {
    // An ordinary set or the Firefox cached-selection fallback revokes
    // permission for content telemetry, even if the bytes are unchanged.
    observedVncSource = "unknown";
    observedVncAt = 0;
  }
  if (uiCopy) {
    recordClipboardActivity({
      kind: "copy_committed", surface: uiCopy[0], method: uiCopy[1], source: uiCopy[0],
    });
  } else if (observedSource) {
    // CLI mouse selection may send a VNC clipboard update without an intentional
    // copy. Firefox content only reaches this path after an explicit shortcut.
    recordClipboardActivity({
      kind: "clipboard_observed", surface: observedSource,
      method: "vnc_clipboard", source: observedSource,
    });
  }
  window.dispatchEvent(new CustomEvent("nerds-internal-clipboard", {
    detail: { text: value, source },
  }));
  return true;
}
