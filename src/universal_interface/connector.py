from __future__ import annotations

from abc import ABC, abstractmethod
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
    RateLimitConfig,
    SubscribeCallback,
    Subscription,
)


class Connector(ABC):
    """Standard connector interface — every external service implements this."""

    name: str
    category: str
    description: str
    version: str = "0.1.0"
    auth_type: AuthType
    capabilities: list[Capability]
    rate_limits: RateLimitConfig | None = None

    @abstractmethod
    async def authenticate(self, credentials: Credentials) -> AuthSession:
        """Validate and establish a session for this connector."""

    @abstractmethod
    async def execute_action(self, action: Action) -> ActionResult:
        """Run a capability; `action.action_id` and `action.params` drive execution."""

    @abstractmethod
    async def fetch_data(self, query: DataQuery) -> DataResult:
        """Normalized pull API for search / listing."""

    async def subscribe(self, event_type: str, callback: SubscribeCallback) -> Subscription:
        """Optional push subscription — default no-op."""
        return Subscription(id=f"{self.name}:{event_type}", event_type=event_type, active=False)

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        ...

    def capability_map(self) -> dict[str, Capability]:
        return {c.action_id: c for c in self.capabilities}
