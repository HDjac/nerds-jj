console.log("[NERDS LLM Logger] background script loaded");

// The NERDS collection server owns this endpoint. It is kept as-is for
// backward compatibility; the payload now carries `service` and `model`
// fields so ChatGPT / Claude / Gemini logs can be distinguished server-side.
const LOG_ENDPOINT = "http://127.0.0.1:60000/log-llm-prompt";

browser.runtime.onMessage.addListener((message) => {
  console.log("[NERDS LLM Logger] background got message:", message);

  if (message.type !== "LLM_PROMPT") {
    return Promise.resolve({ ok: false, error: "Unknown message type" });
  }

  return fetch(LOG_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(message.payload)
  })
    .then(async (response) => {
      const text = await response.text();

      console.log("[NERDS LLM Logger] log response:", response.status, text);

      return {
        ok: response.ok,
        status: response.status,
        body: text
      };
    })
    .catch((error) => {
      console.error("[NERDS LLM Logger] failed to send prompt:", error);

      return {
        ok: false,
        error: String(error)
      };
    });
});