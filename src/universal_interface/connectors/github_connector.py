"""GitHub REST API connector (personal access token or oauth token)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
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


_GITHUB_API = "https://api.github.com"


class GitHubConnector(Connector):
    """Search issues/PRs and inspect the authenticated user via GitHub REST."""

    version = "0.1.0"
    auth_type = AuthType.PAT

    def __init__(self, token: str | None) -> None:
        self.name = "github"
        self.category = "development"
        self.description = (
            "GitHub: search issues/PRs, create issues and comments, view viewer login."
        )
        self._token = (token or "").strip() or None
        self.capabilities = [
            Capability(
                action_id="search_issues",
                name="Search issues",
                description=(
                    "Search GitHub issues across repos you can access. "
                    "Params: q (GitHub search query string)."
                ),
                input_schema={"q": "string"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="search_pull_requests",
                name="Search pull requests",
                description="Search open PRs. Params: q (optional GitHub search qualifiers).",
                input_schema={"q": "string"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="get_viewer",
                name="Authenticated user",
                description="Return the currently authenticated GitHub login.",
                requires_confirmation=False,
            ),
            Capability(
                action_id="create_issue",
                name="Create issue",
                description=(
                    "Open a new GitHub issue. Params: owner, repo, title, "
                    "body (optional markdown)."
                ),
                input_schema={
                    "owner": "string",
                    "repo": "string",
                    "title": "string",
                    "body": "string",
                },
                requires_confirmation=True,
            ),
            Capability(
                action_id="create_issue_comment",
                name="Comment on issue",
                description=(
                    "Add a comment to an issue or PR by numeric id. "
                    "Params: owner, repo, issue_number, body."
                ),
                input_schema={
                    "owner": "string",
                    "repo": "string",
                    "issue_number": "integer",
                    "body": "string",
                },
                requires_confirmation=True,
            ),
        ]

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "UniversalAIInterface/0.1",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        if credentials.api_key:
            self._token = credentials.api_key.strip()
        valid = bool(self._token)
        return AuthSession(connector_name=self.name, valid=valid)

    def _need_token(self) -> ActionResult | None:
        if self._token:
            return None
        return ActionResult(
            success=False,
            message="Missing GitHub token. Set GITHUB_TOKEN or GH_TOKEN (classic PAT or fine-grained with repo scope).",
        )

    async def execute_action(self, action: Action) -> ActionResult:
        denied = self._need_token()
        if denied:
            return denied

        async with httpx.AsyncClient(timeout=45.0) as client:
            if action.action_id == "get_viewer":
                r = await client.get(f"{_GITHUB_API}/user", headers=self._headers())
                if r.status_code != 200:
                    return ActionResult(
                        success=False,
                        message=f"GitHub API error {r.status_code}: {r.text[:500]}",
                    )
                data = r.json()
                return ActionResult(
                    success=True,
                    data={"login": data.get("login"), "html_url": data.get("html_url")},
                    deep_links=[data.get("html_url") or ""],
                )

            if action.action_id == "search_issues":
                q = str(action.params.get("q") or "").strip()
                if not q:
                    return ActionResult(success=False, message="Missing params.q")
                url = f"{_GITHUB_API}/search/issues"
                r = await client.get(
                    url,
                    headers=self._headers(),
                    params={"q": q, "per_page": min(int(action.params.get("per_page") or 20), 100)},
                )
                return self._parse_search_response(r)

            if action.action_id == "search_pull_requests":
                q = str(action.params.get("q") or "").strip() or "is:pr is:open"
                if "is:pr" not in q:
                    q = f"is:pr {q}"
                r = await client.get(
                    f"{_GITHUB_API}/search/issues",
                    headers=self._headers(),
                    params={"q": q, "per_page": min(int(action.params.get("per_page") or 15), 100)},
                )
                return self._parse_search_response(r)

            if action.action_id == "create_issue":
                owner = str(action.params.get("owner") or "").strip()
                repo = str(action.params.get("repo") or "").strip()
                title = str(action.params.get("title") or "").strip()
                body = str(action.params.get("body") or "").strip()
                if not owner or not repo or not title:
                    return ActionResult(
                        success=False,
                        message="Missing owner, repo, or title.",
                    )
                r = await client.post(
                    f"{_GITHUB_API}/repos/{owner}/{repo}/issues",
                    headers=self._headers(),
                    json={"title": title, "body": body or ""},
                )
                if r.status_code not in (200, 201):
                    return ActionResult(
                        success=False,
                        message=f"GitHub create_issue {r.status_code}: {r.text[:500]}",
                    )
                data = r.json()
                url = str(data.get("html_url") or "")
                return ActionResult(
                    success=True,
                    data={"number": data.get("number"), "title": data.get("title"), "url": url},
                    deep_links=[url] if url else [],
                )

            if action.action_id == "create_issue_comment":
                owner = str(action.params.get("owner") or "").strip()
                repo = str(action.params.get("repo") or "").strip()
                num = action.params.get("issue_number")
                body = str(action.params.get("body") or "").strip()
                if not owner or not repo or num is None or not body:
                    return ActionResult(
                        success=False,
                        message="Missing owner, repo, issue_number, or body.",
                    )
                try:
                    num_int = int(num)
                except (TypeError, ValueError):
                    return ActionResult(success=False, message="issue_number must be an integer.")
                r = await client.post(
                    f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{num_int}/comments",
                    headers=self._headers(),
                    json={"body": body},
                )
                if r.status_code not in (200, 201):
                    return ActionResult(
                        success=False,
                        message=f"GitHub comment {r.status_code}: {r.text[:500]}",
                    )
                data = r.json()
                url = str(data.get("html_url") or "")
                return ActionResult(success=True, data={"id": data.get("id")}, deep_links=[url] if url else [])

        return ActionResult(success=False, message=f"Unknown action: {action.action_id}")

    def _parse_search_response(self, r: httpx.Response) -> ActionResult:
        if r.status_code != 200:
            return ActionResult(
                success=False,
                message=f"GitHub search failed {r.status_code}: {r.text[:500]}",
            )
        payload = r.json()
        items = payload.get("items") or []
        return ActionResult(
            success=True,
            data={"total_count": payload.get("total_count"), "items": items[:50]},
            deep_links=[u for it in items if (u := it.get("html_url"))],
        )

    async def fetch_data(self, query: DataQuery) -> DataResult:
        if not self._token:
            return DataResult()
        q_text = (query.text or "").strip()
        search_q = q_text if q_text else "is:open is:issue sort:updated-desc"
        limit = max(1, min(query.limit, 50))

        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.get(
                f"{_GITHUB_API}/search/issues",
                headers=self._headers(),
                params={"q": search_q, "per_page": limit},
            )
            if r.status_code != 200:
                return DataResult()

            payload = r.json()
            items_raw: list[dict[str, Any]] = payload.get("items") or []
            unified: list[UnifiedDataItem] = []
            for it in items_raw[:limit]:
                created = it.get("created_at")
                ts = None
                if isinstance(created, str):
                    try:
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except ValueError:
                        ts = None
                labels = [lbl.get("name", "") for lbl in (it.get("labels") or [])]
                body_preview = (it.get("body") or "")[:800]
                itype = "pull_request" if it.get("pull_request") is not None else "issue"
                unified.append(
                    UnifiedDataItem(
                        id=str(it.get("id", "")),
                        source=self.name,
                        type=itype,
                        title=str(it.get("title") or ""),
                        content=body_preview,
                        author=str((it.get("user") or {}).get("login") or ""),
                        timestamp=ts,
                        url=str(it.get("html_url") or ""),
                        metadata={
                            "state": it.get("state"),
                            "repository_url": it.get("repository_url"),
                            "labels": labels,
                        },
                    )
                )
            return DataResult(items=unified)

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        if not self._token:
            return HealthStatus(
                ok=False,
                message="No GITHUB_TOKEN / GH_TOKEN configured.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(f"{_GITHUB_API}/user", headers=self._headers())
            elapsed = (time.perf_counter() - t0) * 1000
            return HealthStatus(
                ok=r.status_code == 200,
                message="GitHub API reachable" if r.status_code == 200 else f"HTTP {r.status_code}",
                latency_ms=elapsed,
            )
        except Exception as e:
            return HealthStatus(
                ok=False,
                message=str(e)[:200],
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
