/* Release 2B.2 event-time task binding. Metadata only unless explicitly enabled.
 * Fail closed if the active task context is not yet known or has gone stale.
 * Never read host clipboard, retain a text queue, or rebind old events to a new task.
 */
const ENABLED = process.env.REACT_APP_NERDS_CLIPBOARD_INGEST === "1";
const TEXT_ENABLED = process.env.REACT_APP_NERDS_CLIPBOARD_TEXT === "1";
const MAX_CHARS = 2048;
const TRANSFERS = new Set([
  "internal_cli:internal_cli", "internal_cli:internal_browser",
  "internal_browser:internal_cli",
]);
const MAX_CONTEXT_AGE_MS = 8000;
let currentTaskContext = null;
let generation = 0;

function apiBase() {
  if (typeof window === "undefined") return null;
  const match = window.location.pathname.match(/^\/proxy\/([0-9a-f]{12})\/(?:nb\/?)?$/);
  return match ? `/proxy/${match[1]}/` : null;
}

export function eligibleTransfer(source, destination, kind) {
  return kind === "paste_requested" && TRANSFERS.has(`${source}:${destination}`);
}

export async function refreshClipboardTaskContext() {
  if (!ENABLED) return false;
  const base = apiBase();
  if (!base) return false;
  const requestGeneration = ++generation;
  try {
    const reply = await fetch(base + "api/pilot1/browser-context", {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!reply.ok) throw new Error("No active task context");
    const data = await reply.json();
    if (requestGeneration !== generation) return false;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(data.task_run_id || "")) {
      currentTaskContext = null;
      return false;
    }
    currentTaskContext = { taskId: data.task_run_id, base, received: Date.now() };
    return true;
  } catch (_) {
    if (requestGeneration === generation) currentTaskContext = null;
    return false;
  }
}

export async function sendClipboardTelemetry(meta, candidateText) {
  if (!ENABLED) return false;
  const base = apiBase();
  // Snapshot the task before network I/O for this clipboard event.
  const snapshot = currentTaskContext;
  if (!base || !snapshot || snapshot.base !== base ||
      Date.now() - snapshot.received > MAX_CONTEXT_AGE_MS) {
    // Drop this event rather than assign it to a task learned after the action.
    void refreshClipboardTaskContext();
    return false;
  }
  if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function") return false;
  const body = {
    event_id: crypto.randomUUID(),
    expected_task_run_id: snapshot.taskId,
    kind: meta.kind, surface: meta.surface,
    method: meta.method, source: meta.source,
    client_timestamp: meta.occurred_at,
  };
  if (TEXT_ENABLED && eligibleTransfer(meta.source, meta.surface, meta.kind) &&
      typeof candidateText === "string" && candidateText.length > 0) {
    body.text = candidateText.slice(0, MAX_CHARS);
  }
  try {
    const reply = await fetch(base + "log-clipboard-event", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return reply.ok;
  } catch (_) { return false; }
}

if (ENABLED && typeof window !== "undefined") {
  void refreshClipboardTaskContext();
  window.addEventListener("nerds:pilot-task-released", () => {
    ++generation;
    currentTaskContext = null;
    void refreshClipboardTaskContext();
  });
  // A stale task will be rejected independently by the API and database.
  window.setInterval(() => { void refreshClipboardTaskContext(); }, 5000);
}
