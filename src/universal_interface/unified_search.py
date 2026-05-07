from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from universal_interface.models import DataQuery, UnifiedDataItem, UnifiedResult
from universal_interface.registry import ConnectorRegistry


async def universal_query(
    registry: ConnectorRegistry,
    *,
    text: str,
    sources: list[str] | None,
    types: list[str] | None,
    limit: int = 20,
) -> list[UnifiedResult]:
    """Fan-out `fetch_data` to connectors and merge normalized items."""
    names = sources if sources and sources != ["all"] else [c.name for c in registry.all()]
    connectors = [registry.get(n) for n in names]
    connectors = [c for c in connectors if c is not None]

    async def run_one(conn):
        q = DataQuery(text=text or None, limit=limit)
        return await conn.fetch_data(q)

    tasks = [run_one(c) for c in connectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[UnifiedDataItem] = []
    for res in results:
        if isinstance(res, Exception):
            continue
        merged.extend(res.items)

    if types and types != ["all"]:
        allow = set(types)
        merged = [i for i in merged if i.type in allow]

    merged.sort(
        key=lambda x: x.timestamp or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    trimmed = merged[:limit]
    return [UnifiedResult(item=i) for i in trimmed]
