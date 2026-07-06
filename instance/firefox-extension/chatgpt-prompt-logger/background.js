console.log("[NERDS ChatGPT Logger] background script loaded");

browser.runtime.onMessage.addListener((message) => {
  console.log("[NERDS ChatGPT Logger] background got message:", message);

  if (message.type !== "CHATGPT_PROMPT") {
    return Promise.resolve({ ok: false, error: "Unknown message type" });
  }

  return fetch("http://127.0.0.1:60000/log-chatgpt-prompt", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(message.payload)
  })
    .then(async (response) => {
      const text = await response.text();

      console.log("[NERDS ChatGPT Logger] log response:", response.status, text);

      return {
        ok: response.ok,
        status: response.status,
        body: text
      };
    })
    .catch((error) => {
      console.error("[NERDS ChatGPT Logger] failed to send prompt:", error);

      return {
        ok: false,
        error: String(error)
      };
    });
});