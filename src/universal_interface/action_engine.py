from __future__ import annotations

from universal_interface.models import Action, ActionResult
from universal_interface.registry import ConnectorRegistry


async def execute_actions_sequentially(
    registry: ConnectorRegistry,
    actions: list[Action],
) -> list[tuple[Action, ActionResult]]:
    """Run actions in order (Phase 1 — no parallel branches yet)."""
    out: list[tuple[Action, ActionResult]] = []
    for action in actions:
        conn = registry.get(action.connector)
        if conn is None:
            out.append(
                (
                    action,
                    ActionResult(success=False, message=f"Unknown connector: {action.connector}"),
                )
            )
            continue
        result = await conn.execute_action(action)
        out.append((action, result))
    return out
