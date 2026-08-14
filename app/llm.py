"""Thin async wrapper around the Featherless.ai chat-completions API.

Featherless is fully OpenAI-compatible (base URL + bearer key swap), so we
reuse the official `openai` package instead of hand-rolling HTTP calls.
See: https://featherless.ai/docs/quickstart-guide
"""
from __future__ import annotations

import json
import logging
from typing import Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger("agent.llm")

T = TypeVar("T", bound=BaseModel)

_settings = get_settings()

_client = AsyncOpenAI(
    api_key=_settings.featherless_api_key or "unset",
    base_url=_settings.featherless_base_url,
    timeout=60.0,
    max_retries=2,       
)


async def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 600,
) -> str:
    """Plain-text completion — used for drafts and notification copy."""
    response = await _client.chat.completions.create(
        model=_settings.featherless_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


async def complete_structured(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    *,
    temperature: float = 0.0,
    max_tokens: int = 500,
    max_retries: int = 2,
) -> T:
    """Ask the model for JSON matching `schema`, validate it, and retry
    (feeding the validation error back to the model) on failure.

    Open-weight models vary in how strictly they honour "JSON only, no
    prose" instructions, so this defensively strips code fences and gives
    the model a couple of chances to self-correct before giving up.
    """
    schema_hint = (
        "\n\nRespond with ONLY a single JSON object matching this schema. "
        "No prose, no markdown code fences, no explanation before or "
        f"after the JSON:\n{json.dumps(schema.model_json_schema())}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt + schema_hint},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response = await _client.chat.completions.create(
            model=_settings.featherless_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = (response.choices[0].message.content or "").strip()
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()
        try:
            data = json.loads(cleaned)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            logger.warning(
                "structured output attempt %d/%d for %s failed: %s",
                attempt + 1,
                max_retries + 1,
                schema.__name__,
                exc,
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That was not valid JSON matching the schema ({exc}). "
                        "Reply again with corrected JSON only."
                    ),
                }
            )

    raise RuntimeError(
        f"LLM did not return valid {schema.__name__} after {max_retries + 1} attempts"
    ) from last_error