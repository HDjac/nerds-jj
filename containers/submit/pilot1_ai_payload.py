"""Validation for Pilot 1 Firefox prompt observations."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID


def normalize_prompt(data):
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")

    raw_id = data.get("interaction_id")
    try:
        interaction_id = UUID(str(raw_id))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid interaction UUID")

    if interaction_id.version != 4:
        raise ValueError("Expected UUID version 4")

    service = data.get("service")
    if service not in ("chatgpt", "claude", "gemini"):
        raise ValueError("Unsupported AI service")

    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Missing prompt")
    if len(prompt) > 100000:
        raise ValueError("Prompt too large")

    model = data.get("model") or "unknown"
    if not isinstance(model, str) or len(model) > 200:
        raise ValueError("Invalid model")

    url = data.get("url")
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Invalid URL")

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()

    allowed = {
        "chatgpt": host == "chatgpt.com"
                   or host.endswith(".openai.com"),
        "claude": host == "claude.ai",
        "gemini": host == "gemini.google.com",
    }

    if parsed.scheme != "https" or not allowed[service]:
        raise ValueError("Unexpected AI website")

    timestamp = data.get("client_timestamp")
    if timestamp is not None:
        if not isinstance(timestamp, str) or len(timestamp) > 64:
            raise ValueError("Invalid timestamp")
        try:
            parsed_time = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        except ValueError:
            raise ValueError("Invalid timestamp")
        if parsed_time.tzinfo is None:
            raise ValueError("Timestamp must include timezone")

    return {
        "event_key": f"ai:{interaction_id}",
        "service": service,
        "model": model,
        "prompt_text": prompt,
        "page_host": host,
        "client_timestamp": timestamp,
        "capture_method": "firefox_extension_prompt",
    }
