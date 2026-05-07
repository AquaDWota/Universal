"""Read-only filesystem access within configured roots."""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

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

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "dist",
        "build",
    }
)


class FilesystemConnector(Connector):
    """List and read files under allowed directories only."""

    version = "0.1.0"
    auth_type = AuthType.NONE

    def __init__(
        self,
        roots: list[Path],
        *,
        max_depth: int = 6,
        max_read_bytes: int = 262_144,
    ) -> None:
        self.name = "filesystem"
        self.category = "productivity"
        self.description = (
            "Read files and list directories under configured roots (sandboxed paths)."
        )
        self._roots = [r.resolve() for r in roots]
        self._max_depth = max(1, min(max_depth, 32))
        self._max_read_bytes = max(1024, min(max_read_bytes, 8 * 1024 * 1024))
        self.capabilities = [
            Capability(
                action_id="read_file",
                name="Read file",
                description="Read UTF-8 text from a path under an allowed root. Params: path (relative or absolute within roots).",
                input_schema={"path": "string"},
                requires_confirmation=False,
            ),
            Capability(
                action_id="list_directory",
                name="List directory",
                description="List immediate children. Params: path (optional, default root).",
                input_schema={"path": "string"},
                requires_confirmation=False,
            ),
        ]

    async def authenticate(self, credentials: Credentials) -> AuthSession:
        return AuthSession(connector_name=self.name, valid=True)

    def _resolve_under_roots(self, raw: str) -> Path | None:
        raw = raw.strip() or "."
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            for root in self._roots:
                try:
                    resolved.relative_to(root)
                    return resolved
                except ValueError:
                    continue
            return None

        for root in self._roots:
            joined = (root / candidate).resolve()
            try:
                joined.relative_to(root)
                return joined
            except ValueError:
                continue
        return None

    def _blocking_scan(self, fragment: str, limit: int) -> list[tuple[Path, Path, float]]:
        frag = fragment.lower().strip()
        words = [w for w in re.split(r"\s+", frag) if len(w) >= 2]

        def file_matches(stem: str, fn: str) -> bool:
            if not frag:
                return True
            hay = f"{stem} {fn}".lower()
            if frag in hay:
                return True
            return any(w in hay for w in words)

        hits: list[tuple[Path, Path, float]] = []
        for root in self._roots:
            if not root.exists():
                continue
            base_depth = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
                cur = Path(dirpath)
                depth = len(cur.parts) - base_depth
                if depth > self._max_depth:
                    dirnames[:] = []
                    continue
                for fn in filenames:
                    if fn.startswith("."):
                        continue
                    fp = cur / fn
                    try:
                        rel = fp.relative_to(root)
                    except ValueError:
                        continue
                    stem = str(rel)
                    if not file_matches(stem, fn):
                        continue
                    try:
                        mtime = fp.stat().st_mtime
                    except OSError:
                        continue
                    hits.append((fp, rel, mtime))
                    if len(hits) >= limit * 4:
                        break
                if len(hits) >= limit * 4:
                    break
            if len(hits) >= limit * 4:
                break
        hits.sort(key=lambda x: -x[2])
        return hits[:limit]

    async def fetch_data(self, query: DataQuery) -> DataResult:
        fragment = (query.text or "").strip()
        limit = max(1, min(query.limit, 100))

        def run_scan() -> list[tuple[Path, Path, float]]:
            if fragment:
                return self._blocking_scan(fragment, limit)
            roots_existing = [r for r in self._roots if r.exists()]
            out: list[tuple[Path, Path, float]] = []
            for root in roots_existing[:5]:
                try:
                    for child in sorted(root.iterdir(), key=lambda p: p.name.lower())[:50]:
                        try:
                            if child.is_file() and not child.name.startswith("."):
                                rel = child.relative_to(root)
                                out.append((child, rel, child.stat().st_mtime))
                        except OSError:
                            continue
                except OSError:
                    continue
                if len(out) >= limit:
                    break
            out.sort(key=lambda x: -x[2])
            return out[:limit]

        pairs = await asyncio.to_thread(run_scan)
        items: list[UnifiedDataItem] = []
        for fp, rel, mtime in pairs[:limit]:
            ts = datetime.fromtimestamp(mtime, tz=UTC)
            items.append(
                UnifiedDataItem(
                    id=str(rel),
                    source=self.name,
                    type="file",
                    title=str(rel),
                    content="",
                    author="",
                    timestamp=ts,
                    url=f"file://{fp}",
                    metadata={"size": fp.stat().st_size if fp.exists() else None},
                )
            )
        return DataResult(items=items)

    async def execute_action(self, action: Action) -> ActionResult:
        if action.action_id == "read_file":
            path_raw = str(action.params.get("path") or "").strip()
            if not path_raw:
                return ActionResult(success=False, message="Missing params.path")
            target = self._resolve_under_roots(path_raw)
            if target is None:
                return ActionResult(success=False, message="Path escapes allowed roots.")
            if not target.is_file():
                return ActionResult(success=False, message="Not a file or missing.")
            try:
                data = target.read_bytes()[: self._max_read_bytes]
                text = data.decode("utf-8", errors="replace")
            except OSError as e:
                return ActionResult(success=False, message=str(e))
            return ActionResult(
                success=True,
                data={
                    "path": str(target),
                    "content": text,
                    "truncated": target.stat().st_size > len(data),
                },
            )

        if action.action_id == "list_directory":
            path_raw = str(action.params.get("path") or ".").strip()
            target = self._resolve_under_roots(path_raw)
            if target is None:
                return ActionResult(success=False, message="Path escapes allowed roots.")
            if not target.is_dir():
                return ActionResult(success=False, message="Not a directory.")
            entries: list[dict[str, str | bool]] = []
            try:
                for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                    if child.name.startswith("."):
                        continue
                    entries.append(
                        {
                            "name": child.name,
                            "is_dir": child.is_dir(),
                            "path": str(child),
                        }
                    )
            except OSError as e:
                return ActionResult(success=False, message=str(e))
            return ActionResult(success=True, data={"entries": entries[:500]})

        return ActionResult(success=False, message=f"Unknown action: {action.action_id}")

    async def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        ok = any(r.exists() for r in self._roots)
        return HealthStatus(
            ok=ok,
            message="filesystem roots OK" if ok else "No configured roots exist on disk.",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
