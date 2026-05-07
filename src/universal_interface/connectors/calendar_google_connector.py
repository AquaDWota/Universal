"""Google Calendar API using a saved OAuth user token (read-only)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarGoogleConnector(Connector):
    """Primary calendar events via OAuth token JSON on disk."""

    version = "0.1.0"
    auth_type = AuthType.OAUTH2

    def __init__(self, token_path: str | Path) -> None:
        self.name = "calendar_google"
        self.category = "productivity"
        self.description = (
            "Google Calendar (read-only): OAuth token JSON path from GOOGLE_CALENDAR_TOKEN_PATH."
        )
        self._token_path = Path(token_path).expanduser().resolve()
        self.capabilities = [
            Capability(
                action_id="list_primary_events",
                name="Primary calendar events",
                description=(
                    "List upcoming events from the primary calendar. Params: days (default 7), max (default 25)."
                ),
                input_schema={"days": "integer", "max": "integer"},
                requires_confirmation=False,
            ),
        ]

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self._token_path.is_file():
            return None
        creds = Credentials.from_authorized_user_file(str(self._token_path), _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json())
        return creds if creds.valid else None

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        ok = self._credentials() is not None
        return AuthSession(connector_name=self.name, valid=ok)

    def _sync_list_events(self, days: int, mx: int) -> list[dict[str, Any]]:
        from googleapiclient.discovery import build

        creds = self._credentials()
        if creds is None:
            return []
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = datetime.now(tz=UTC)
        t_min = now.isoformat()
        t_max = (now + timedelta(days=days)).isoformat()
        ev = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=t_min,
                timeMax=t_max,
                maxResults=min(mx, 100),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return ev.get("items") or []

    async def execute_action(self, action: Action) -> ActionResult:
        if action.action_id != "list_primary_events":
            return ActionResult(success=False, message=f"Unknown action: {action.action_id}")
        days = int(action.params.get("days") or 7)
        mx = int(action.params.get("max") or 25)
        days = max(1, min(days, 90))
        try:
            items = await asyncio.to_thread(self._sync_list_events, days, mx)
            slim = [
                {
                    "summary": i.get("summary"),
                    "start": (i.get("start") or {}).get("dateTime") or (i.get("start") or {}).get("date"),
                    "htmlLink": i.get("htmlLink"),
                    "status": i.get("status"),
                }
                for i in items
            ]
            links = [s["htmlLink"] for s in slim if s.get("htmlLink")]
            return ActionResult(success=True, data={"events": slim}, deep_links=links)
        except Exception as e:
            return ActionResult(success=False, message=str(e)[:500])

    async def fetch_data(self, query: DataQuery) -> DataResult:
        q_text = (query.text or "").lower().strip()
        try:
            raw_items = await asyncio.to_thread(self._sync_list_events, 14, min(query.limit * 3, 50))
        except Exception:
            return DataResult()

        unified: list[UnifiedDataItem] = []
        for i in raw_items:
            summary = str(i.get("summary") or "Event")
            blob = summary.lower()
            desc = str(i.get("description") or "")[:600]
            blob += desc.lower()
            if q_text and q_text not in blob:
                continue
            start_d = i.get("start") or {}
            ts_raw = start_d.get("dateTime") or start_d.get("date")
            ts = None
            if isinstance(ts_raw, str):
                try:
                    if "T" in ts_raw:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    else:
                        ts = datetime.fromisoformat(ts_raw).replace(tzinfo=UTC)
                except ValueError:
                    ts = None
            url = str(i.get("htmlLink") or "")
            unified.append(
                UnifiedDataItem(
                    id=str(i.get("id") or summary),
                    source=self.name,
                    type="event",
                    title=summary,
                    content=desc,
                    author="google_calendar",
                    timestamp=ts,
                    url=url,
                    metadata={"status": i.get("status")},
                )
            )
            if len(unified) >= query.limit:
                break
        return DataResult(items=unified[: query.limit])

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._token_path.is_file():
            return HealthStatus(
                ok=False,
                message=f"Token file missing: {self._token_path}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        p = self._token_path
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ok = bool(data.get("refresh_token") or data.get("token"))
            return HealthStatus(
                ok=ok,
                message="Token file present" if ok else "Token JSON incomplete.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as e:
            return HealthStatus(
                ok=False,
                message=str(e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
