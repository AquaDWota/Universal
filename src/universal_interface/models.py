from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class AuthType(str, Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    PAT = "personal_access_token"
    USERNAME_PASSWORD = "username_password"
    SSH_KEY = "ssh_key"
    CERTIFICATE = "certificate"
    BROWSER_SESSION = "browser_session"
    NONE = "none"


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"
    EXECUTE = "execute"


class ActionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionKind(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    TRANSFER = "transfer"


class Capability(BaseModel):
    action_id: str
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    estimated_duration: str = "~1s"
    cost: float | None = None


class Credentials(BaseModel):
    api_key: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    username: str | None = None
    password: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AuthSession(BaseModel):
    connector_name: str
    valid: bool = True
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Action(BaseModel):
    connector: str
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    kind: ActionKind = ActionKind.READ
    risk: ActionRisk = ActionRisk.LOW


class ActionResult(BaseModel):
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    deep_links: list[str] = Field(default_factory=list)


class DataQuery(BaseModel):
    text: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 20


class Attachment(BaseModel):
    id: str
    name: str
    mime_type: str | None = None
    url: str | None = None


class Relation(BaseModel):
    type: str
    target_id: str
    target_source: str | None = None


class UnifiedDataItem(BaseModel):
    id: str
    source: str
    type: str
    title: str
    content: str = ""
    author: str = ""
    timestamp: datetime | None = None
    url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[Attachment] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class DataResult(BaseModel):
    items: list[UnifiedDataItem] = Field(default_factory=list)
    cursor: str | None = None


class HealthStatus(BaseModel):
    ok: bool
    message: str = ""
    latency_ms: float | None = None


class RateLimitConfig(BaseModel):
    requests_per_minute: int | None = None
    burst: int | None = None


class Subscription(BaseModel):
    id: str
    event_type: str
    active: bool = True


class UnifiedResult(BaseModel):
    item: UnifiedDataItem
    score: float | None = None


class IntentPlan(BaseModel):
    """Structured output from the intent router."""

    summary: str = ""
    needs_clarification: bool = False
    clarification_question: str | None = None
    actions: list[Action] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class TimeRange(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


# Type alias used by Connector.subscribe signatures
SubscribeCallback = Callable[[dict[str, Any]], Any]
