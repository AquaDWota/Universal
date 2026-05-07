"""Linear GraphQL connector (API key)."""

from __future__ import annotations

import time
from typing import Any

import httpx

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

_LINEAR_GQL = "https://api.linear.app/graphql"

_ASSIGNED_ISSUES_QUERY = """
query AssignedIssues($first: Int!) {
  viewer {
    assignedIssues(first: $first) {
      nodes {
        id
        identifier
        title
        url
      }
    }
  }
}
"""

_TEAMS_QUERY = """
query Teams {
  teams(first: 50) {
    nodes { id name key }
  }
}
"""

_ISSUE_CREATE = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier url title }
  }
}
"""


class LinearConnector(Connector):
    """Assigned issues, team discovery, and issue creation on Linear."""

    version = "0.1.0"
    auth_type = AuthType.API_KEY

    def __init__(self, api_key: str | None, default_team_id: str | None = None) -> None:
        self.name = "linear"
        self.category = "development"
        self.description = (
            "Linear: assigned issues, list teams, create issues (team id from config or params)."
        )
        self._api_key = (api_key or "").strip() or None
        tid = (default_team_id or "").strip()
        self._default_team_id = tid or None
        self.capabilities = [
            Capability(
                action_id="list_assigned_issues",
                name="Assigned issues",
                description=(
                    "Return issues assigned to you. Params: first (optional max count, default 25)."
                ),
                input_schema={"first": "integer"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="list_teams",
                name="List teams",
                description="Return workspace teams with ids for issueCreate.",
                requires_confirmation=False,
            ),
            Capability(
                action_id="create_issue",
                name="Create issue",
                description=(
                    "Open an issue on a team. Params: title, description (optional), "
                    "team_id (optional if connectors.linear.team_id is set)."
                ),
                input_schema={
                    "title": "string",
                    "description": "string",
                    "team_id": "string",
                },
                requires_confirmation=True,
            ),
        ]

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = self._api_key
        return h

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        if credentials.api_key:
            self._api_key = credentials.api_key.strip()
        return AuthSession(connector_name=self.name, valid=bool(self._api_key))

    def _need_key(self) -> ActionResult | None:
        if self._api_key:
            return None
        return ActionResult(
            success=False,
            message="Missing LINEAR_API_KEY environment variable.",
        )

    async def _post_gql(self, client: httpx.AsyncClient, query: str, variables: dict[str, Any]):
        return await client.post(
            _LINEAR_GQL,
            headers=self._headers(),
            json={"query": query, "variables": variables},
        )

    async def execute_action(self, action: Action) -> ActionResult:
        denied = self._need_key()
        if denied:
            return denied

        async with httpx.AsyncClient(timeout=45.0) as client:
            if action.action_id == "list_assigned_issues":
                first = int(action.params.get("first") or 25)
                first = max(1, min(first, 100))
                r = await self._post_gql(client, _ASSIGNED_ISSUES_QUERY, {"first": first})
                if r.status_code != 200:
                    return ActionResult(
                        success=False,
                        message=f"Linear HTTP {r.status_code}: {r.text[:400]}",
                    )
                payload = r.json()
                if payload.get("errors"):
                    err = payload["errors"][0].get("message", payload["errors"])
                    return ActionResult(success=False, message=str(err)[:500])
                nodes = (
                    (((payload.get("data") or {}).get("viewer") or {}).get("assignedIssues") or {}).get(
                        "nodes"
                    )
                    or []
                )
                slim = [
                    {
                        "identifier": n.get("identifier"),
                        "title": n.get("title"),
                        "url": n.get("url"),
                    }
                    for n in nodes
                ]
                links = [s["url"] for s in slim if s.get("url")]
                return ActionResult(success=True, data={"issues": slim}, deep_links=links)

            if action.action_id == "list_teams":
                r = await self._post_gql(client, _TEAMS_QUERY, {})
                if r.status_code != 200:
                    return ActionResult(
                        success=False,
                        message=f"Linear HTTP {r.status_code}: {r.text[:400]}",
                    )
                payload = r.json()
                if payload.get("errors"):
                    err = payload["errors"][0].get("message", payload["errors"])
                    return ActionResult(success=False, message=str(err)[:500])
                nodes = (((payload.get("data") or {}).get("teams") or {}).get("nodes")) or []
                teams = [
                    {"id": n.get("id"), "name": n.get("name"), "key": n.get("key")}
                    for n in nodes
                ]
                return ActionResult(success=True, data={"teams": teams})

            if action.action_id == "create_issue":
                title = str(action.params.get("title") or "").strip()
                description = str(action.params.get("description") or "").strip()
                team_id = str(action.params.get("team_id") or "").strip() or (
                    self._default_team_id or ""
                )
                if not title:
                    return ActionResult(success=False, message="Missing params.title.")
                if not team_id:
                    return ActionResult(
                        success=False,
                        message=(
                            "Missing team id — set connectors.linear.team_id in config "
                            "or pass params.team_id (UUID)."
                        ),
                    )
                inp: dict[str, Any] = {"teamId": team_id, "title": title}
                if description:
                    inp["description"] = description
                r = await self._post_gql(client, _ISSUE_CREATE, {"input": inp})
                if r.status_code != 200:
                    return ActionResult(
                        success=False,
                        message=f"Linear HTTP {r.status_code}: {r.text[:400]}",
                    )
                payload = r.json()
                if payload.get("errors"):
                    err = payload["errors"][0].get("message", payload["errors"])
                    return ActionResult(success=False, message=str(err)[:500])
                ic = ((payload.get("data") or {}).get("issueCreate")) or {}
                if not ic.get("success"):
                    return ActionResult(success=False, message=str(ic)[:500])
                issue = ic.get("issue") or {}
                url = str(issue.get("url") or "")
                return ActionResult(
                    success=True,
                    data={
                        "identifier": issue.get("identifier"),
                        "title": issue.get("title"),
                        "url": url,
                    },
                    deep_links=[url] if url else [],
                )

        return ActionResult(success=False, message=f"Unknown action: {action.action_id}")

    async def fetch_data(self, query: DataQuery) -> DataResult:
        denied = self._need_key()
        if denied:
            return DataResult()

        first = max(1, min(query.limit, 50))
        q_text = (query.text or "").lower().strip()

        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await self._post_gql(client, _ASSIGNED_ISSUES_QUERY, {"first": first})
            if r.status_code != 200:
                return DataResult()
            payload = r.json()
            if payload.get("errors"):
                return DataResult()
            nodes = (
                (((payload.get("data") or {}).get("viewer") or {}).get("assignedIssues") or {}).get(
                    "nodes"
                )
                or []
            )

        items: list[UnifiedDataItem] = []
        for n in nodes:
            title = str(n.get("title") or "")
            ident = str(n.get("identifier") or "")
            if q_text and q_text not in title.lower() and q_text not in ident.lower():
                continue
            items.append(
                UnifiedDataItem(
                    id=str(n.get("id", "")),
                    source=self.name,
                    type="task",
                    title=f"{ident} {title}".strip(),
                    content="",
                    author="linear",
                    timestamp=None,
                    url=str(n.get("url") or ""),
                    metadata={},
                )
            )
            if len(items) >= query.limit:
                break

        return DataResult(items=items[: query.limit])

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._api_key:
            return HealthStatus(
                ok=False,
                message="No LINEAR_API_KEY configured.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await self._post_gql(client, "query { viewer { id } }", {})
            elapsed = (time.perf_counter() - t0) * 1000
            data = r.json()
            ok = r.status_code == 200 and not data.get("errors")
            msg = "Linear OK" if ok else str(data.get("errors") or r.status_code)
            return HealthStatus(ok=ok, message=str(msg)[:200], latency_ms=elapsed)
        except Exception as e:
            return HealthStatus(
                ok=False,
                message=str(e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
