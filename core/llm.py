"""Structured LLM calls for RegWatch.

Every agentic node (diff, impact, action, query) needs the model to return JSON that
validates against a Pydantic schema. The previous code did ``json.loads(...)`` inside a
bare ``except`` that silently dropped a detected change on a single malformed response —
the #1 demo-reliability risk. ``complete_structured`` replaces that pattern with:

1. Groq JSON mode (``response_format={"type": "json_object"}``) so the model must emit JSON.
2. Pydantic validation against the caller's schema.
3. Self-correction: on an invalid response the validation error is fed back so the model
   can fix it, instead of the result being thrown away.
4. Backoff retry on transient API errors (rate limit / network).
"""

from __future__ import annotations

import json
import time
from typing import TypeVar

from groq import Groq
from pydantic import BaseModel, ValidationError

from config.settings import get_secret

DEFAULT_MODEL = "llama-3.3-70b-versatile"

T = TypeVar("T", bound=BaseModel)


def get_groq_client() -> Groq:
    """Build a Groq client from env or Streamlit secrets."""
    key = get_secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is required.")
    return Groq(api_key=key)


def complete_structured(
    client: Groq,
    prompt: str,
    schema: type[T],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 512,
    max_attempts: int = 3,
    system: str | None = None,
) -> T | None:
    """Call Groq in JSON mode and validate the reply against ``schema``.

    Returns a validated instance of ``schema``, or ``None`` if every attempt fails.
    The prompt must mention "JSON" (Groq's JSON mode requires it) — all RegWatch
    prompts already do.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_attempts):
        raw = ""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            return schema.model_validate_json(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            # The response was reachable but wrong — let the model correct itself.
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That response was not valid for the required schema: {exc}. "
                        "Respond again with ONLY a valid JSON object that satisfies it."
                    ),
                }
            )
        except Exception:
            # Transient API failure (rate limit, network) — back off and retry.
            time.sleep(min(2**attempt, 8))

    return None
