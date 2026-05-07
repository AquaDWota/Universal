from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from universal_interface.config import AppConfig, EnvSettings, load_config
from universal_interface.connectors.bootstrap import populate_registry
from universal_interface.database import create_engine_and_session
from universal_interface.registry import ConnectorRegistry
from universal_interface.vector_store import VectorStore


class AppContext:
    """Wires registry, persistence, and optional vector search."""

    def __init__(
        self,
        *,
        config: AppConfig,
        env: EnvSettings,
        registry: ConnectorRegistry,
        engine: AsyncEngine,
        session_factory: async_sessionmaker,
        vector_store: VectorStore | None,
    ) -> None:
        self.config = config
        self.env = env
        self.registry = registry
        self.engine = engine
        self.session_factory = session_factory
        self.vector_store = vector_store

    @classmethod
    async def create(cls, env: EnvSettings | None = None) -> AppContext:
        env = env or EnvSettings()
        cfg = load_config(env=env)
        if env.inference is not None:
            cfg.ai.inference = env.inference
        data_dir = env.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)

        db_path = data_dir / "universal.db"
        engine, session_factory = await create_engine_and_session(db_path)

        registry = ConnectorRegistry()
        populate_registry(registry, cfg)

        vector_store: VectorStore | None = None
        mem = cfg.memory or {}
        if mem.get("vector_db") == "chromadb":
            persist = Path(mem.get("storage_path") or data_dir).expanduser().resolve()
            try:
                vector_store = VectorStore(persist_directory=persist)
            except Exception:
                vector_store = None

        return cls(
            config=cfg,
            env=env,
            registry=registry,
            engine=engine,
            session_factory=session_factory,
            vector_store=vector_store,
        )

    async def shutdown(self) -> None:
        await self.engine.dispose()
