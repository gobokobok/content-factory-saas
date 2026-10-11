"""Text generation behind one small interface (P-INT1, D112).

`LLMClient.complete(system, user, model=, max_tokens=)` returns the model's text.
Two adapters, plain `httpx` for OpenAI and the existing `anthropic` SDK for Claude —
no new dependency. Workers that only need "a system prompt and a user message in,
text out" (YouTube metadata today) take an `LLMClient`, so the tenant's default
provider of the Thinking models block decides who answers.

Workers that rely on provider-specific features — adaptive thinking, streaming,
prompt caching — stay on the Anthropic SDK directly; they are not routed through
this interface. Error messages never include a key.
"""

from typing import Protocol

import anthropic
import httpx

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
LLM_PROVIDER_IDS = ("anthropic", "openai_llm")


class LLMError(Exception):
    """Raised when a provider cannot answer; the message is safe to show the operator."""


class LLMClient(Protocol):
    """One system prompt and one user message in, the model's text out."""

    async def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        """Return the model's answer as text."""
        ...


class AnthropicLLM:
    """Claude through the Anthropic SDK."""

    def __init__(self, api_key: str, timeout_s: float = 60.0) -> None:
        """Keep the key and the request timeout."""
        self._api_key, self._timeout = api_key, timeout_s

    async def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        """Call messages.create with the system prompt cached and return the first text block."""
        client = anthropic.AsyncAnthropic(api_key=self._api_key, timeout=self._timeout)
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic could not answer: {type(exc).__name__}") from exc
        return "".join(b.text for b in message.content if getattr(b, "type", "text") == "text")


class OpenAILLM:
    """OpenAI chat completions over httpx."""

    def __init__(self, api_key: str, timeout_s: float = 60.0, base_url: str = OPENAI_CHAT_URL) -> None:
        """Keep the key, the request timeout and the endpoint."""
        self._api_key, self._timeout, self._url = api_key, timeout_s, base_url

    async def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        """POST one chat completion and return the first choice's text."""
        payload = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI could not be reached: {type(exc).__name__}") from exc
        if response.status_code != 200:
            detail = ""
            try:
                detail = str((response.json().get("error") or {}).get("message") or "")[:200]
            except Exception:
                pass
            raise LLMError(f"OpenAI answered {response.status_code}" + (f": {detail}" if detail else ""))
        try:
            text = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("OpenAI returned an answer that could not be read.") from exc
        if not (text or "").strip():
            raise LLMError("OpenAI returned an empty answer.")
        return str(text)


def build_llm_client(provider_id: str, api_key: str) -> LLMClient:
    """The adapter for a Thinking-models provider id; LLMError for one that has none."""
    if provider_id == "anthropic":
        return AnthropicLLM(api_key)
    if provider_id == "openai_llm":
        return OpenAILLM(api_key)
    raise LLMError(f"No text-generation adapter for {provider_id!r}.")
