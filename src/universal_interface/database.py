from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Base(DeclarativeBase):
    pass


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    connector: Mapped[str] = mapped_column(String(128))
    action_id: Mapped[str] = mapped_column(String(256))
    params_json: Mapped[str] = mapped_column(Text())
    success: Mapped[str] = mapped_column(String(8))  # "true" / "false"
    result_json: Mapped[str] = mapped_column(Text(), default="{}")


def _sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"


async def create_engine_and_session(db_path: Path):
    engine = create_async_engine(_sqlite_url(db_path), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


async def record_audit(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    connector: str,
    action_id: str,
    params: dict,
    success: bool,
    result: dict,
) -> None:
    async with session_factory() as session:
        row = AuditLogRow(
            created_at=datetime.now(tz=UTC),
            connector=connector,
            action_id=action_id,
            params_json=json.dumps(params, default=str),
            success="true" if success else "false",
            result_json=json.dumps(result, default=str),
        )
        session.add(row)
        await session.commit()
