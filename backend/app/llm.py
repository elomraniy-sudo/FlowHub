"""Thin client for the Compass LLM gateway (OpenAI-compatible /chat/completions).
All prompts ask for strict JSON so results can be stored/structured."""
import json
import re
from typing import Any

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> Any:
    """Tolerant JSON extraction: handles ```json fences and leading prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise LLMError(f"No JSON in LLM response: {text[:200]}")
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            elif ch == '"': in_str = True
            elif ch in "{[": depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
        raise LLMError("Unbalanced JSON in LLM response")


def chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 4000) -> str:
    if settings.LLM_MOCK:
        from .llm_mock import mock_chat
        return mock_chat(messages)
    if not settings.COMPASS_API_KEY:
        raise LLMError("COMPASS_API_KEY is not set (or set LLM_MOCK=true)")
    url = settings.COMPASS_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.COMPASS_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": settings.COMPASS_MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=settings.LLM_TIMEOUT)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"LLM request failed: {e}") from e
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected LLM response shape: {str(data)[:300]}") from e


def chat_json(system: str, user: str, retries: int = 2, **kw) -> Any:
    """Chat and parse JSON; on malformed output, retry (then ask the model to repair its own answer)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last: Exception | None = None
    content = ""
    for attempt in range(retries + 1):
        try:
            if attempt == 0:
                content = chat(messages, **kw)
            else:
                repair = messages + [{"role": "assistant", "content": content},
                                     {"role": "user", "content": "Your previous answer was not valid JSON "
                                      f"({last}). Output the SAME content again as one strictly valid JSON object, "
                                      "no prose, no markdown fences."}]
                content = chat(repair, temperature=0, max_tokens=kw.get("max_tokens", 4000))
            return _extract_json(content)
        except (LLMError, json.JSONDecodeError) as e:
            last = e
    raise LLMError(f"LLM did not return valid JSON after {retries + 1} attempts: {last}")
