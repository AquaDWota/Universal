"""Fetch public HTTPS documents (strict SSRF guards)."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

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


_TITLE_RE = re.compile(r"<title[^>]*>([^<]{1,300})", re.I)


class HttpFetchConnector(Connector):
    """GET HTTPS URLs that pass SSRF checks (optional http when explicitly allowed)."""

    version = "0.1.0"
    auth_type = AuthType.NONE

    def __init__(self, *, max_bytes: int = 512_000, allow_http: bool = False) -> None:
        self.name = "http_fetch"
        self.category = "research"
        self.description = (
            "Fetch a public URL over HTTPS (SSRF-filtered). Optional HTTP allowed via config."
        )
        self._max_bytes = max(4096, min(max_bytes, 5 * 1024 * 1024))
        self._allow_http = allow_http
        self.capabilities = [
            Capability(
                action_id="fetch_url",
                name="Fetch URL",
                description=(
                    "GET a URL and return trimmed text + title hint. Params: url (https)."
                ),
                input_schema={"url": "string"},
                requires_confirmation=False,
            ),
        ]

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        return AuthSession(connector_name=self.name, valid=True)

    async def _fetch(self, url: str) -> tuple[int, str, str]:
        async with httpx.AsyncClient(
            timeout=25.0,
            follow_redirects=True,
            headers={"User-Agent": "UniversalAIInterface/0.1"},
        ) as client:
            r = await client.get(url)
            raw = r.content[: self._max_bytes]
            text = raw.decode("utf-8", errors="replace")
            title_m = _TITLE_RE.search(text)
            title = title_m.group(1).strip() if title_m else ""
            return r.status_code, title, text

    async def execute_action(self, action: Action) -> ActionResult:
        if action.action_id != "fetch_url":
            return ActionResult(success=False, message=f"Unknown action: {action.action_id}")
        url = str(action.params.get("url") or "").strip()
        if not url:
            return ActionResult(success=False, message="Missing params.url")
        if not is_safe_https_url(url, allow_http=self._allow_http):
            return ActionResult(success=False, message="URL failed safety checks (HTTPS-only).")
        try:
            status, title, text = await self._fetch(url)
            snippet = " ".join(text.split())[:4000]
            return ActionResult(
                success=True,
                data={
                    "status_code": status,
                    "title": title,
                    "snippet": snippet,
                    "truncated": len(text) >= self._max_bytes,
                },
                deep_links=[url],
            )
        except Exception as e:
            return ActionResult(success=False, message=str(e)[:400])

    async def fetch_data(self, query: DataQuery) -> DataResult:
        raw = (query.text or "").strip()
        if not raw:
            return DataResult()
        parsed = urlparse(raw.split()[0])
        if parsed.scheme not in {"http", "https"}:
            return DataResult()
        url = raw.split()[0]
        if not is_safe_https_url(url, allow_http=self._allow_http):
            return DataResult()
        try:
            status, title, text = await self._fetch(url)
            snippet = " ".join(text.split())[:2000]
            item = UnifiedDataItem(
                id=url,
                source=self.name,
                type="web_page",
                title=title or url,
                content=f"[HTTP {status}] {snippet}",
                author="",
                timestamp=datetime.now(tz=UTC),
                url=url,
                metadata={"status_code": status},
            )
            return DataResult(items=[item])
        except Exception:
            return DataResult()

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        return HealthStatus(
            ok=True,
            message="http_fetch ready (no persistent upstream).",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
