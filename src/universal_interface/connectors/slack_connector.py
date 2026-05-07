"""Slack Web API (bot token)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

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


class SlackConnector(Connector):
    """Post messages and read channel metadata via a Slack bot token."""

    version = "0.1.0"
    auth_type = AuthType.API_KEY

    def __init__(self, bot_token: str | None) -> None:
        self.name = "slack"
        self.category = "communication"
        self.description = (
            "Slack: list channels, read recent messages, post as the bot (scopes required)."
        )
        self._token = (bot_token or "").strip() or None
        self.capabilities = [
            Capability(
                action_id="list_public_channels",
                name="List channels",
                description="List non-archived public channels (paginated slice). Params: limit (max 200).",
                input_schema={"limit": "integer"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="channel_history",
                name="Channel history",
                description=(
                    "Fetch recent messages from a channel. Params: channel (ID like C…), limit."
                ),
                input_schema={"channel": "string", "limit": "integer"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="post_message",
                name="Post message",
                description="Post text to a channel. Params: channel, text.",
                input_schema={"channel": "string", "text": "string"},
                requires_confirmation=True,
            ),
        ]

    def _client(self) -> WebClient | None:
        return WebClient(token=self._token) if self._token else None

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        if credentials.api_key:
            self._token = credentials.api_key.strip()
        return AuthSession(connector_name=self.name, valid=bool(self._token))

    def _need_token(self) -> ActionResult | None:
        if self._token:
            return None
        return ActionResult(
            success=False,
            message="Missing SLACK_BOT_TOKEN (Bot User OAuth Token xoxb-…).",
        )

    async def execute_action(self, action: Action) -> ActionResult:
        denied = self._need_token()
        if denied:
            return denied
        client = self._client()
        assert client is not None

        def wrap(fn):
            return asyncio.to_thread(fn)

        try:
            if action.action_id == "list_public_channels":
                lim = min(int(action.params.get("limit") or 100), 200)

                def _run():
                    out = []
                    cursor = None
                    while len(out) < lim:
                        kwargs: dict[str, Any] = {
                            "types": "public_channel",
                            "exclude_archived": True,
                            "limit": min(200, lim - len(out)),
                        }
                        if cursor:
                            kwargs["cursor"] = cursor
                        resp = client.conversations_list(**kwargs)
                        out.extend(resp.get("channels") or [])
                        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                        if not cursor:
                            break
                    return out[:lim]

                channels = await wrap(_run)
                slim = [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "topic": (c.get("topic") or {}).get("value"),
                    }
                    for c in channels
                ]
                return ActionResult(success=True, data={"channels": slim})

            if action.action_id == "channel_history":
                ch = str(action.params.get("channel") or "").strip()
                if not ch:
                    return ActionResult(success=False, message="Missing params.channel")
                lim = min(int(action.params.get("limit") or 20), 100)

                def _hist():
                    resp = client.conversations_history(channel=ch, limit=lim)
                    return resp.get("messages") or []

                messages = await wrap(_hist)
                return ActionResult(success=True, data={"messages": messages})

            if action.action_id == "post_message":
                ch = str(action.params.get("channel") or "").strip()
                text = str(action.params.get("text") or "").strip()
                if not ch or not text:
                    return ActionResult(success=False, message="Missing channel or text.")

                def _post():
                    return client.chat_postMessage(channel=ch, text=text)

                resp = await wrap(_post)
                ts = resp.get("ts")
                return ActionResult(
                    success=True,
                    data={"ts": ts, "channel": resp.get("channel")},
                )

        except SlackApiError as e:
            return ActionResult(success=False, message=str(e.response or e)[:500])

        return ActionResult(success=False, message=f"Unknown action: {action.action_id}")

    async def fetch_data(self, query: DataQuery) -> DataResult:
        denied = self._need_token()
        if denied:
            return DataResult()
        client = self._client()
        assert client is not None
        q = (query.text or "").lower().strip()

        def _list():
            resp = client.conversations_list(
                types="public_channel",
                exclude_archived=True,
                limit=min(200, max(query.limit * 5, 50)),
            )
            return resp.get("channels") or []

        try:
            channels = await asyncio.to_thread(_list)
        except SlackApiError:
            return DataResult()

        items: list[UnifiedDataItem] = []
        for c in channels:
            name = str(c.get("name") or "")
            cid = str(c.get("id") or "")
            topic = str((c.get("topic") or {}).get("value") or "")
            hay = f"{name} {topic}".lower()
            if q and q not in hay:
                continue
            items.append(
                UnifiedDataItem(
                    id=cid,
                    source=self.name,
                    type="channel",
                    title=f"#{name}",
                    content=topic[:1200],
                    author="slack",
                    timestamp=None,
                    url="",
                    metadata={"channel_id": cid},
                )
            )
            if len(items) >= query.limit:
                break

        return DataResult(items=items[: query.limit])

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._token:
            return HealthStatus(
                ok=False,
                message="No SLACK_BOT_TOKEN configured.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        client = self._client()
        assert client is not None

        def _auth():
            return client.auth_test()

        try:
            await asyncio.to_thread(_auth)
            return HealthStatus(
                ok=True,
                message="Slack auth.test OK",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except SlackApiError as e:
            return HealthStatus(
                ok=False,
                message=str(e.response or e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
