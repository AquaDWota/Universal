from __future__ import annotations

import json
from typing import Any

from universal_interface.config import AIConfig, resolved_chat_model


async def complete_json(
    ai: AIConfig,
    *,
    system: str,
    user: str,
) -> dict[str, Any]:
    """Ask the configured model for a JSON object."""
    from litellm import acompletion

    model, _mode = resolved_chat_model(ai)
    base: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": ai.temperature,
        "max_tokens": ai.max_tokens,
    }
    try:
        resp = await acompletion(**base, response_format={"type": "json_object"})
    except Exception:
        resp = await acompletion(**base)
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


async def complete_text(
    ai: AIConfig,
    *,
    system: str,
    user: str,
) -> str:
    from litellm import acompletion

    model, _mode = resolved_chat_model(ai)
    resp = await acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=ai.temperature,
        max_tokens=ai.max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
