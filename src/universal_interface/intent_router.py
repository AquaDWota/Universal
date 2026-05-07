from __future__ import annotations

import json
import os
import re
from typing import Any

from universal_interface.config import AIConfig
from universal_interface.llm import complete_json
from universal_interface.models import Action, ActionKind, ActionRisk, IntentPlan
from universal_interface.registry import ConnectorRegistry


_ROUTER_SYSTEM = """You are the Intent Router for the Universal AI Interface.
Given user text and the list of available connectors, respond with a SINGLE JSON object:
{
  "summary": "short natural language summary of what you understood",
  "needs_clarification": false,
  "clarification_question": null,
  "actions": [
    {
      "connector": "connector_name",
      "action_id": "capability action_id",
      "params": {},
      "kind": "read|create|update|delete|execute|transfer",
      "risk": "low|medium|high|critical"
    }
  ],
  "search_queries": ["optional strings for unified search across connectors"]
}
Rules:
- Prefer READ/search_queries when the user asks to find, list, search, or summarize available data.
- Use actions only when the user clearly wants to change external systems or run a tool.
- For greetings or smalltalk with no tool need, return empty actions and empty search_queries.
- Never invent connectors not listed.
"""


def _has_llm_credentials() -> bool:
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("AZURE_API_KEY")
        or os.getenv("LITELLM_PROXY_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )


def _parse_action_blob(blob: dict[str, Any]) -> Action:
    kind = ActionKind.READ
    risk = ActionRisk.LOW
    try:
        if blob.get("kind"):
            kind = ActionKind(str(blob["kind"]))
    except ValueError:
        kind = ActionKind.READ
    try:
        if blob.get("risk"):
            risk = ActionRisk(str(blob["risk"]))
    except ValueError:
        risk = ActionRisk.LOW
    return Action(
        connector=str(blob.get("connector", "")),
        action_id=str(blob.get("action_id", "")),
        params=dict(blob.get("params") or {}),
        kind=kind,
        risk=risk,
    )


def heuristic_plan(user_text: str, registry: ConnectorRegistry) -> IntentPlan:
    t = user_text.lower().strip()
    names = {c.name for c in registry.all()}

    if "ping" in t and "mock_service" in names:
        return IntentPlan(
            summary="Run connector health ping.",
            actions=[
                Action(
                    connector="mock_service",
                    action_id="ping",
                    kind=ActionKind.READ,
                    risk=ActionRisk.LOW,
                )
            ],
        )

    add_note = re.search(r"add\s+note\s*[:\-]?\s*(.+)", t, re.I | re.S)
    if add_note and "mock_service" in names:
        return IntentPlan(
            summary="Store a note in the demo connector.",
            actions=[
                Action(
                    connector="mock_service",
                    action_id="add_note",
                    params={"text": add_note.group(1).strip()},
                    kind=ActionKind.CREATE,
                    risk=ActionRisk.MEDIUM,
                )
            ],
        )

    search_like = any(k in t for k in ("search", "find", "show", "list", "what", "summarize"))
    if search_like or len(t) > 3:
        q = user_text.strip()
        return IntentPlan(
            summary="Search unified normalized data across connected services.",
            search_queries=[q],
        )

    return IntentPlan(summary="No matching heuristic.", needs_clarification=False)


async def route_intent(
    user_text: str,
    *,
    registry: ConnectorRegistry,
    ai: AIConfig,
) -> IntentPlan:
    if _has_llm_credentials():
        user = (
            "Available connectors:\n"
            f"{registry.describe_for_prompt()}\n\n"
            f'User message:\n"""{user_text}"""'
        )
        try:
            data = await complete_json(ai, system=_ROUTER_SYSTEM, user=user)
            actions = [_parse_action_blob(a) for a in data.get("actions") or []]
            actions = [a for a in actions if a.connector and a.action_id]
            return IntentPlan(
                summary=str(data.get("summary") or ""),
                needs_clarification=bool(data.get("needs_clarification")),
                clarification_question=data.get("clarification_question"),
                actions=actions,
                search_queries=[str(s) for s in data.get("search_queries") or []],
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
        except Exception:
            # LiteLLM / network errors — fall back
            pass

    return heuristic_plan(user_text, registry)
