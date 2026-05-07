from __future__ import annotations

from typing import Iterable

from universal_interface.connector import Connector


class ConnectorRegistry:
    """Registers connectors by name for routing and discovery."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector

    def register_all(self, connectors: Iterable[Connector]) -> None:
        for c in connectors:
            self.register(c)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    def all(self) -> list[Connector]:
        return list(self._connectors.values())

    def describe_for_prompt(self) -> str:
        lines: list[str] = []
        for c in sorted(self._connectors.values(), key=lambda x: x.name):
            cap_lines = "\n".join(
                f"    - {cap.action_id}: {cap.description}" for cap in c.capabilities
            )
            lines.append(f"- {c.name} ({c.category}): {c.description}\n{cap_lines}")
        return "\n".join(lines)
