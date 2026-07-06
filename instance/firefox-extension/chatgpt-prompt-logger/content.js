console.log("[NERDS ChatGPT Logger] content script loaded");

function getPromptText() {
  const textarea = document.querySelector("textarea");
  if (textarea && textarea.value.trim()) {
    return textarea.value.trim();
  }

  const editable = document.querySelector("[contenteditable='true']");
  if (editable && editable.innerText.trim()) {
    return editable.innerText.trim();
  }

  return "";
}

async function sendPrompt(promptText) {
  if (!promptText) return;

  const payload = {
    prompt: promptText,
    url: window.location.href,
    timestamp: new Date().toISOString()
  };

  console.log("[NERDS ChatGPT Logger] prompt captured:", payload);

  try {
    const response = await browser.runtime.sendMessage({
      type: "CHATGPT_PROMPT",
      payload
    });

    console.log("[NERDS ChatGPT Logger] background response:", response);
  } catch (error) {
    console.error("[NERDS ChatGPT Logger] failed to message background:", error);
  }
}

document.addEventListener(
  "keydown",
  function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      const promptText = getPromptText();
      sendPrompt(promptText);
    }
  },
  true
);

document.addEventListener(
  "click",
  function (event) {
    const button = event.target.closest("button");
    if (!button) return;

    const promptText = getPromptText();
    sendPrompt(promptText);
  },
  true
);