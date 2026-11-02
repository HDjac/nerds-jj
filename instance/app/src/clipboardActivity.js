/* Release 2B.1: strictly metadata-only, in-memory observation of UI actions.
 * NO network requests, clipboard text, text length, hashes, URLs, credentials,
 * participant IDs, localStorage, or persistence. Backend ingestion is 2B.2.
 * Observation is not proof that Firefox/xterm accepted or inserted text.
 */
import { sendClipboardTelemetry } from "./clipboardTelemetry";

const KINDS = new Set([
  "copy_committed", "copy_requested", "clipboard_observed", "paste_requested",
  "external_paste_blocked", "host_paste_shortcut_blocked",
]);
const SURFACES = new Set([
  "task_sidebar", "fuzzing_guide", "internal_cli", "internal_browser", "other_internal",
]);
const METHODS = new Set([
  "copy_button", "sidebar_keyboard", "vnc_clipboard", "ctrl_shortcut",
  "meta_shortcut", "shift_insert", "other_internal",
]);
const SOURCES = new Set([
  "task_sidebar", "fuzzing_guide", "internal_cli", "internal_browser",
  "other_internal", "unknown",
]);
const MAX_EVENTS = 100;
let sequence = 0;
let records = [];

export function recordClipboardActivity({ kind, surface, method, source = "unknown", text }) {
  // Avoid putting arbitrary application/user strings in the event payload.
  if (!KINDS.has(kind) || !SURFACES.has(surface) || !METHODS.has(method) ||
      !SOURCES.has(source)) return false;
  if (typeof window === "undefined") return false;
  const event = Object.freeze({
    kind, surface, method, source, sequence: ++sequence,
    occurred_at: new Date().toISOString(),
  });
  records.push(event);
  if (records.length > MAX_EVENTS) records.shift();
  window.dispatchEvent(new CustomEvent("nerds:clipboard-activity", { detail: event }));
  // Content is NOT placed in event details, history, localStorage or console.
  void sendClipboardTelemetry(event, text);
  return true;
}

// Read-only diagnostic snapshot for unit tests. Never exposed as a window API.
export function getClipboardActivitySnapshot() {
  return records.map(item => ({ ...item }));
}

export function clearClipboardActivity() {
  records = [];
  sequence = 0;
}

if (typeof window !== "undefined") {
  window.addEventListener("nerds:pilot-task-released", clearClipboardActivity);
}

// Use only at a handler that positively detects and rejects a host paste.
// Neither a missing internal clipboard nor Shift+Insert alone proves a host attempt.
export function recordConfirmedExternalPasteBlock(surface, method) {
  return recordClipboardActivity({
    kind: "external_paste_blocked", surface, method, source: "unknown",
  });
}
