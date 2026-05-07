"""Demo connector — simulates a connected service without external APIs."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from universal_interface.connector import Connector
from universal_interface.models import (
    Action,
    ActionResult,
    AuthSession,
    AuthType,
    Capability,
    Credentials,
    DataQuery,
    DataResult,
    HealthStatus,
    UnifiedDataItem,
)


class MockServiceConnector(Connector):
    """Phase-1 placeholder: inbox-style items for wiring chat + router + search."""

    name = "mock_service"
    category = "productivity"
    description = "Local demo connector returning sample tasks and messages."
    version = "0.1.0"
    auth_type = AuthType.NONE
    capabilities = [
        Capability(
            action_id="ping",
            name="Ping",
            description="Health check for the mock connector.",
            requires_confirmation=False,
        ),
        Capability(
            action_id="add_note",
            name="Add note",
            description="Append a short note to the mock inbox.",
            input_schema={"text": "string"},
            requires_confirmation=False,
        ),
    ]

    def __init__(self) -> None:
        self._notes: list[str] = []
        self._session: AuthSession | None = None

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        self._session = AuthSession(connector_name=self.name, valid=True)
        return self._session

    async def execute_action(self, action: Action) -> ActionResult:
        if action.action_id == "ping":
            return ActionResult(success=True, data={"pong": True, "connector": self.name})
        if action.action_id == "add_note":
            text = str(action.params.get("text", "")).strip()
            if not text:
                return ActionResult(success=False, message="Missing text parameter.")
            self._notes.append(text)
            return ActionResult(
                success=True,
                data={"stored": text, "count": len(self._notes)},
            )
        return ActionResult(success=False, message=f"Unknown action: {action.action_id}")

    async def fetch_data(self, query: DataQuery) -> DataResult:
        now = datetime.now(tz=UTC)
        items: list[UnifiedDataItem] = [
            UnifiedDataItem(
                id="mock-1",
                source=self.name,
                type="task",
                title="Review Universal AI Interface spec",
                content="Connector framework + intent router baseline.",
                author="you",
                timestamp=now,
                url="",
                metadata={"priority": "high"},
            ),
            UnifiedDataItem(
                id="mock-2",
                source=self.name,
                type="message",
                title="Team channel digest",
                content="Example: two mentions overnight (mock).",
                author="mock-bot",
                timestamp=now,
            ),
        ]
        q = (query.text or "").lower().strip()
        if q:
            filtered = [
                i
                for i in items
                if q in i.title.lower() or q in i.content.lower() or q in i.type.lower()
            ]
            filtered.extend(
                UnifiedDataItem(
                    id=f"note-{i}",
                    source=self.name,
                    type="note",
                    title=f"Note {i + 1}",
                    content=n,
                    timestamp=now,
                )
                for i, n in enumerate(self._notes)
                if q in n.lower()
            )
            # If nothing matched, still return baseline items so unified search stays useful.
            items = filtered if filtered else items
        limit = max(1, min(query.limit, 100))
        return DataResult(items=items[:limit])

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        ok = self._session is None or self._session.valid
        elapsed = (time.perf_counter() - t0) * 1000
        return HealthStatus(ok=ok, message="mock_service OK", latency_ms=elapsed)
