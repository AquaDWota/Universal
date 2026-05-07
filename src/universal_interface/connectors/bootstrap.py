"""Register connectors from AppConfig + environment (tokens never required in YAML)."""

from __future__ import annotations

import os
from pathlib import Path

from universal_interface.config import AppConfig
from universal_interface.connectors.calendar_google_connector import CalendarGoogleConnector
from universal_interface.connectors.calendar_ics_connector import CalendarIcsConnector
from universal_interface.connectors.email_imap_connector import EmailImapConnector
from universal_interface.connectors.filesystem_connector import FilesystemConnector
from universal_interface.connectors.github_connector import GitHubConnector
from universal_interface.connectors.http_fetch_connector import HttpFetchConnector
from universal_interface.connectors.linear_connector import LinearConnector
from universal_interface.connectors.mock_service import MockServiceConnector
from universal_interface.connectors.slack_connector import SlackConnector
from universal_interface.registry import ConnectorRegistry


def _dump(entry) -> dict:
    return entry.model_dump() if entry is not None else {}


def populate_registry(registry: ConnectorRegistry, cfg: AppConfig) -> None:
    """Attach all enabled connectors. Secrets come from environment variables only."""

    mock_entry = cfg.connectors.get("mock_service")
    if mock_entry is None or mock_entry.enabled:
        registry.register(MockServiceConnector())

    fs_entry = cfg.connectors.get("filesystem")
    if fs_entry and fs_entry.enabled:
        raw = _dump(fs_entry)
        roots_raw = raw.get("roots") or ["."]
        roots = [Path(str(r)).expanduser().resolve() for r in roots_raw]
        max_depth = int(raw.get("max_depth") or 6)
        max_read = int(raw.get("max_read_bytes") or 262_144)
        registry.register(
            FilesystemConnector(roots, max_depth=max_depth, max_read_bytes=max_read)
        )

    gh_entry = cfg.connectors.get("github")
    if gh_entry and gh_entry.enabled:
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        registry.register(GitHubConnector(token=token))

    linear_entry = cfg.connectors.get("linear")
    if linear_entry and linear_entry.enabled:
        raw = _dump(linear_entry)
        key = os.getenv("LINEAR_API_KEY")
        team_raw = raw.get("team_id")
        team_id = str(team_raw).strip() if team_raw else None
        registry.register(LinearConnector(api_key=key, default_team_id=team_id))

    hf_entry = cfg.connectors.get("http_fetch")
    if hf_entry and hf_entry.enabled:
        raw = _dump(hf_entry)
        registry.register(
            HttpFetchConnector(
                max_bytes=int(raw.get("max_bytes") or 512_000),
                allow_http=bool(raw.get("allow_http", False)),
            )
        )

    slack_entry = cfg.connectors.get("slack")
    if slack_entry and slack_entry.enabled:
        registry.register(SlackConnector(os.getenv("SLACK_BOT_TOKEN")))

    imap_entry = cfg.connectors.get("email_imap")
    if imap_entry and imap_entry.enabled:
        raw = _dump(imap_entry)
        host = os.getenv("IMAP_HOST") or str(raw.get("host") or "imap.gmail.com")
        user = os.getenv("IMAP_USER") or ""
        password = os.getenv("IMAP_PASSWORD") or ""
        folder = os.getenv("IMAP_FOLDER") or str(raw.get("folder") or "INBOX")
        port = int(os.getenv("IMAP_PORT") or raw.get("port") or 993)
        fetch_limit = int(raw.get("fetch_limit") or 40)
        if user and password:
            registry.register(
                EmailImapConnector(
                    host,
                    user,
                    password,
                    folder=folder,
                    port=port,
                    fetch_limit=fetch_limit,
                )
            )

    ics_entry = cfg.connectors.get("calendar_ics")
    if ics_entry and ics_entry.enabled:
        raw = _dump(ics_entry)
        urls = raw.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        url_list = [str(u).strip() for u in urls if str(u).strip()]
        if url_list:
            registry.register(CalendarIcsConnector(url_list))

    gcal_entry = cfg.connectors.get("calendar_google")
    if gcal_entry and gcal_entry.enabled:
        tp = os.getenv("GOOGLE_CALENDAR_TOKEN_PATH")
        if tp:
            registry.register(CalendarGoogleConnector(tp))
