"""Provider-agnostic LLM helper.

Preferred path: the official `anthropic` SDK with ANTHROPIC_API_KEY (portable
to any host). Fallback: Emergent's universal key via `emergentintegrations`
when ANTHROPIC_API_KEY is not set.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EMERGENT_LLM_KEY"))


async def complete(system: str, user_text: str, max_tokens: int = 4096) -> Optional[str]:
    """Return the assistant's text for a single-turn prompt, or None on failure."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return await _via_anthropic(anthropic_key, system, user_text, max_tokens)

    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if emergent_key:
        return await _via_emergent(emergent_key, system, user_text)

    logger.warning("No LLM key configured (ANTHROPIC_API_KEY or EMERGENT_LLM_KEY)")
    return None


async def _via_anthropic(api_key: str, system: str, user_text: str, max_tokens: int) -> Optional[str]:
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content)
    except Exception as e:
        logger.warning("Anthropic LLM call failed: %s", e)
        return None


async def _via_emergent(api_key: str, system: str, user_text: str) -> Optional[str]:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        logger.warning("emergentintegrations import failed: %s", e)
        return None
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"llm-{uuid.uuid4()}",
            system_message=system,
        ).with_model("anthropic", MODEL)
        return await chat.send_message(UserMessage(text=user_text))
    except Exception as e:
        logger.warning("Emergent LLM call failed: %s", e)
        return None
