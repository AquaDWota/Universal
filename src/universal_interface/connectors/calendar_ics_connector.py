"""Subscribe to public iCalendar (.ics) feeds."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from icalendar import Calendar

from universal_interface.connector import Connector
from universal_interface.connectors.url_safety import is_safe_https_url
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


class CalendarIcsConnector(Connector):
    """Fetch recurring/public calendar URLs and expose upcoming events."""

    version = "0.1.0"
    auth_type = AuthType.NONE

    def __init__(self, urls: list[str]) -> None:
        self.name = "calendar_ics"
        self.category = "productivity"
        self.description = (
            "Calendar via HTTPS .ics URLs (Google ‘secret address’, Outlook publish, etc.)."
        )
        self._urls = [u.strip() for u in urls if u.strip()]
        self.capabilities = [
            Capability(
                action_id="list_upcoming",
                name="Upcoming events",
                description=(
                    "Reload ICS URLs and return events within the next N days. "
                    "Params: days (default 14)."
                ),
                input_schema={"days": "integer"},
                requires_confirmation=False,
            ),
        ]

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        return AuthSession(connector_name=self.name, valid=bool(self._urls))

    def _parse_calendar_bytes(self, data: bytes) -> Calendar | None:
        try:
            return Calendar.from_ical(data)
        except Exception:
            return None

    def _events_window(self, cal: Calendar, horizon_days: int) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC)
        horizon_end = now + timedelta(days=max(1, min(horizon_days, 120)))
        out: list[dict[str, Any]] = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            try:
                dtstart = component.get("dtstart")
                if dtstart is None:
                    continue
                ev_dt = dtstart.dt
                if hasattr(ev_dt, "tzinfo") and ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=UTC)
                elif hasattr(ev_dt, "date") and not hasattr(ev_dt, "hour"):
                    ev_dt = datetime.combine(ev_dt, datetime.min.time(), tzinfo=UTC)
                if isinstance(ev_dt, datetime) and ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=UTC)
                if not isinstance(ev_dt, datetime):
                    continue
                if ev_dt < now or ev_dt > horizon_end:
                    continue
                summary = str(component.get("summary") or "Event")
                description = str(component.get("description") or "")[:800]
                location = str(component.get("location") or "")
                uid = str(component.get("uid") or f"{summary}-{ev_dt.isoformat()}")
                out.append(
                    {
                        "start": ev_dt,
                        "summary": summary,
                        "description": description,
                        "location": location,
                        "uid": uid,
                    }
                )
            except Exception:
                continue
        out.sort(key=lambda e: e["start"])
        return out[:200]

    async def _load_all(self) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
            for url in self._urls:
                if not is_safe_https_url(url, allow_http=False):
                    continue
                try:
                    r = await client.get(url, headers={"User-Agent": "UniversalAIInterface/0.1"})
                    if r.status_code != 200:
                        continue
                    cal = await asyncio.to_thread(self._parse_calendar_bytes, r.content)
                    if cal is None:
                        continue
                    merged.extend(self._events_window(cal, 60))
                except Exception:
                    continue
        merged.sort(key=lambda e: e["start"])
        return merged[:200]

    async def execute_action(self, action: Action) -> ActionResult:
        if not self._urls:
            return ActionResult(success=False, message="No calendar URLs configured.")
        if action.action_id != "list_upcoming":
            return ActionResult(success=False, message=f"Unknown action: {action.action_id}")
        days = int(action.params.get("days") or 14)
        events = await self._load_all()
        cutoff = datetime.now(tz=UTC) + timedelta(days=days)
        slim = [e for e in events if e["start"] <= cutoff][:80]
        return ActionResult(success=True, data={"events": slim})

    async def fetch_data(self, query: DataQuery) -> DataResult:
        if not self._urls:
            return DataResult()
        q_text = (query.text or "").lower().strip()
        events = await self._load_all()
        items: list[UnifiedDataItem] = []
        for e in events[: query.limit * 3]:
            hay = f"{e['summary']} {e['description']} {e['location']}".lower()
            if q_text and q_text not in hay:
                continue
            url_str = ""
            loc = e.get("location") or ""
            if isinstance(loc, str) and loc.startswith("http"):
                url_str = loc
            elif isinstance(loc, str) and urlparse(loc).scheme in {"http", "https"}:
                url_str = loc
            items.append(
                UnifiedDataItem(
                    id=e["uid"][:128],
                    source=self.name,
                    type="event",
                    title=e["summary"],
                    content=(e["description"] or "")[:1200],
                    author="calendar",
                    timestamp=e["start"],
                    url=url_str,
                    metadata={"location": e.get("location")},
                )
            )
            if len(items) >= query.limit:
                break
        return DataResult(items=items[: query.limit])

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._urls:
            return HealthStatus(
                ok=False,
                message="No ICS URLs in config connectors.calendar_ics.urls.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        try:
            events = await self._load_all()
            ok = len(events) >= 0
            return HealthStatus(
                ok=ok,
                message=f"Loaded {len(events)} upcoming window items.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as e:
            return HealthStatus(
                ok=False,
                message=str(e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
