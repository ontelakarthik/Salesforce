"""AI provider abstraction for email-draft/call-prep generation (BRD §5.6/
§5.7 — AI-1/AI-2, CI-1/CI-2) and lead scoring (BRD SC-2). A narrow Protocol,
with Cohere as the concrete provider wired up now (their free tier) —
swapping to Anthropic/OpenAI/Azure OpenAI later means writing one more
small class here, never touching crm_service.py's prompt-building or route
code.

No live web search here: Cohere retired their "connectors" web-search
mechanism (removed from /v1/chat on 2025-09-15, no direct hosted
replacement — see https://docs.cohere.com/docs/deprecations) and adding a
separate search provider (e.g. Tavily) to restore it was explicitly
deferred. Drafting/scoring instead reasons from in-system lead data (and,
for whatever the model already knows about well-known companies) with an
explicit "never invent specifics you can't back up" instruction in the
prompts — see crm_service.py.

`get_llm_client()` is a FastAPI dependency like any repository factory (see
repositories/_base.py's pattern) — routes take it via `Depends(get_llm_client)`,
and tests override it via `app.dependency_overrides[get_llm_client]` with a
fake, since there's no real API key in dev/CI and this is the one place in
the codebase that calls out over the network.
"""
from typing import Protocol

import httpx

from src.config.config_reader import get_settings
from src.utils.exceptions import DomainError

_COHERE_CHAT_V2_URL = "https://api.cohere.com/v2/chat"
_TIMEOUT_SECONDS = 20.0


class LLMClient(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's raw text response to one system+user turn."""
        ...


class CohereLLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = httpx.post(
                _COHERE_CHAT_V2_URL,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DomainError(
                "AI_PROVIDER_ERROR",
                f"Cohere returned {exc.response.status_code}: {exc.response.text[:300]}", 502) from exc
        except httpx.HTTPError as exc:
            raise DomainError("AI_PROVIDER_ERROR", f"Could not reach the AI provider: {exc}", 502) from exc

        return _extract_text(response.json())


def _extract_text(data: dict) -> str:
    """Cohere's v2 Chat response nests text under message.content[0].text;
    parsed defensively (a couple of alternate shapes checked)."""
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
            return content[0]["text"]
    if isinstance(data.get("text"), str):
        return data["text"]
    raise DomainError("AI_RESPONSE_INVALID", "Could not parse a text response from the AI provider.", 502)


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if not settings.COHERE_API_KEY:
        raise DomainError(
            "AI_PROVIDER_NOT_CONFIGURED",
            "COHERE_API_KEY is not set — add it to .env to enable AI-assisted drafting.", 503)
    return CohereLLMClient(settings.COHERE_API_KEY, settings.COHERE_MODEL)


def get_optional_llm_client() -> LLMClient | None:
    """Same as get_llm_client(), but for call sites where "no AI key
    configured" should degrade to a deterministic result instead of failing
    the whole request — see crm_service.generate_next_best_action(), which
    falls back to a rule-based recommendation rather than 503ing Radar's
    core worklist feature over a missing API key (same reasoning as
    email_client.get_optional_email_sender())."""
    try:
        return get_llm_client()
    except DomainError:
        return None
