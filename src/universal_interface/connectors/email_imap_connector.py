"""Read-only IMAP inbox (works with Gmail using an app password)."""

from __future__ import annotations

import asyncio
import email
import imaplib
import time
from datetime import UTC, datetime
from email.header import decode_header
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


def _decode_mime_header(value: str) -> str:
    parts = decode_header(value or "")
    out: list[str] = []
    for frag, enc in parts:
        if isinstance(frag, bytes):
            out.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(frag)
    return "".join(out)


class EmailImapConnector(Connector):
    """Pull recent messages from an IMAP folder (READ-only)."""

    version = "0.1.0"
    auth_type = AuthType.USERNAME_PASSWORD

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        *,
        folder: str = "INBOX",
        port: int = 993,
        fetch_limit: int = 40,
    ) -> None:
        self.name = "email_imap"
        self.category = "communication"
        self.description = (
            "IMAP inbox reader — uses IMAP_HOST/IMAP_USER/IMAP_PASSWORD (e.g. Gmail app password)."
        )
        self._host = host.strip()
        self._user = user.strip()
        self._password = password
        self._folder = folder.strip() or "INBOX"
        self._port = port
        self._fetch_limit = max(5, min(fetch_limit, 200))
        self.capabilities = [
            Capability(
                action_id="fetch_recent",
                name="Fetch recent mail",
                description=(
                    "Download headers/snippet of recent messages. Params: limit (optional)."
                ),
                input_schema={"limit": "integer"},
                requires_confirmation=False,
            ),
        ]

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        return AuthSession(
            connector_name=self.name,
            valid=bool(self._host and self._user and self._password),
        )

    def _configured(self) -> bool:
        return bool(self._host and self._user and self._password)

    def _fetch_sync(self, limit: int) -> list[dict[str, Any]]:
        conn = imaplib.IMAP4_SSL(self._host, self._port)
        try:
            conn.login(self._user, self._password)
            typ, _ = conn.select(self._folder, readonly=True)
            if typ != "OK":
                return []
            typ, data = conn.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()
            pick = ids[-limit:] if len(ids) > limit else ids
            rows: list[dict[str, Any]] = []
            for mid in reversed(pick):
                typ, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_hdr = msg_data[0][1]
                if not isinstance(raw_hdr, bytes):
                    continue
                msg = email.message_from_bytes(raw_hdr)
                subj = _decode_mime_header(msg.get("Subject") or "")
                sender = _decode_mime_header(msg.get("From") or "")
                date_hdr = msg.get("Date") or ""
                rows.append(
                    {
                        "id": mid.decode(),
                        "subject": subj,
                        "from": sender,
                        "date": date_hdr,
                    }
                )
            return rows
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    async def execute_action(self, action: Action) -> ActionResult:
        if not self._configured():
            return ActionResult(
                success=False,
                message="Configure IMAP_HOST, IMAP_USER, IMAP_PASSWORD (environment).",
            )
        if action.action_id != "fetch_recent":
            return ActionResult(success=False, message=f"Unknown action: {action.action_id}")
        lim = int(action.params.get("limit") or self._fetch_limit)
        lim = max(1, min(lim, 100))
        try:
            rows = await asyncio.to_thread(self._fetch_sync, lim)
            return ActionResult(success=True, data={"messages": rows})
        except imaplib.IMAP4.error as e:
            return ActionResult(success=False, message=str(e)[:400])

    async def fetch_data(self, query: DataQuery) -> DataResult:
        if not self._configured():
            return DataResult()
        q_text = (query.text or "").lower().strip()
        lim = max(1, min(query.limit, self._fetch_limit))
        try:
            rows = await asyncio.to_thread(self._fetch_sync, lim)
        except imaplib.IMAP4.error:
            return DataResult()

        items: list[UnifiedDataItem] = []
        for row in rows:
            blob = f"{row['subject']} {row['from']}".lower()
            if q_text and q_text not in blob:
                continue
            ts = None
            try:
                dt = email.utils.parsedate_to_datetime(row["date"])
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                ts = dt
            except (TypeError, ValueError):
                ts = None
            items.append(
                UnifiedDataItem(
                    id=str(row["id"]),
                    source=self.name,
                    type="email",
                    title=row["subject"] or "(no subject)",
                    content=row["from"],
                    author=row["from"],
                    timestamp=ts,
                    url="",
                    metadata={"imap_folder": self._folder},
                )
            )
            if len(items) >= query.limit:
                break
        return DataResult(items=items)

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._configured():
            return HealthStatus(
                ok=False,
                message="Missing IMAP_HOST / IMAP_USER / IMAP_PASSWORD.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        try:

            def _noop():
                conn = imaplib.IMAP4_SSL(self._host, self._port)
                conn.login(self._user, self._password)
                conn.logout()

            await asyncio.to_thread(_noop)
            return HealthStatus(ok=True, message="IMAP login OK", latency_ms=(time.perf_counter() - t0) * 1000)
        except Exception as e:
            return HealthStatus(
                ok=False,
                message=str(e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
