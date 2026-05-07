from __future__ import annotations

from universal_interface.action_engine import execute_actions_sequentially
from universal_interface.app_context import AppContext
from universal_interface.config import llm_inference_enabled
from universal_interface.database import record_audit
from universal_interface.intent_router import route_intent
from universal_interface.llm import complete_text
from universal_interface.unified_search import universal_query


async def handle_turn(ctx: AppContext, user_text: str) -> str:
    """Single chat turn: route intent, search, execute actions, optionally synthesize."""
    plan = await route_intent(user_text, registry=ctx.registry, ai=ctx.config.ai)

    parts: list[str] = []
    if plan.summary:
        parts.append(plan.summary)

    if plan.needs_clarification and plan.clarification_question:
        parts.append(plan.clarification_question)
        return "\n\n".join(parts)

    search_lines: list[str] = []
    for q in plan.search_queries or ([] if plan.actions else [user_text]):
        results = await universal_query(ctx.registry, text=q, sources=["all"], types=["all"], limit=12)
        if ctx.vector_store and results:
            try:
                ctx.vector_store.upsert_items([r.item for r in results])
            except Exception:
                # Embedding/model download failures should not block chat.
                pass
        for r in results:
            ts = r.item.timestamp.isoformat() if r.item.timestamp else ""
            search_lines.append(
                f"- [{r.item.source}/{r.item.type}] **{r.item.title}** — {r.item.content[:300]}{'…' if len(r.item.content) > 300 else ''} ({ts})"
            )
    if search_lines:
        parts.append("### Unified search\n" + "\n".join(search_lines))

    if plan.actions:
        executed = await execute_actions_sequentially(ctx.registry, plan.actions)
        action_lines: list[str] = []
        for action, result in executed:
            await record_audit(
                ctx.session_factory,
                connector=action.connector,
                action_id=action.action_id,
                params=action.params,
                success=result.success,
                result=result.model_dump(),
            )
            status = "ok" if result.success else "failed"
            msg = result.message or ""
            action_lines.append(
                f"- `{action.connector}.{action.action_id}` → **{status}** {msg}\n  ```json\n  {result.model_dump_json()[:800]}\n  ```"
            )
        parts.append("### Actions\n" + "\n".join(action_lines))

    body = "\n\n".join(parts) if parts else "_No structured output._"

    if llm_inference_enabled(ctx.config.ai):
        sys = (
            "You are the Universal AI Interface response synthesizer. "
            "Combine the structured notes into a concise, helpful reply for the user. "
            "Preserve important links if present. Do not invent facts."
        )
        try:
            return await complete_text(
                ctx.config.ai,
                system=sys,
                user=f"User asked:\n{user_text}\n\nSystem notes:\n{body}",
            )
        except Exception:
            pass

    return body
