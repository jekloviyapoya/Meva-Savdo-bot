"""Baza ulanishi va sxemani avtomatik moslashtirish."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from sqlalchemy import Enum as SAEnum, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = logging.getLogger("db")

engine = create_async_engine(settings.async_database_url, echo=False, pool_pre_ping=True)
SessionMaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def session_scope():
    async with SessionMaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _sync_columns(sync_conn) -> None:
    """Modelga qo'shilgan yangi ustunlarni mavjud jadvallarga qo'shadi.

    `create_all` faqat yo'q jadvalni yaratadi — mavjud jadvalga ustun qo'shmaydi.
    Shu sabab kod yangilanganda eski baza «column ... does not exist» xatosini
    bergan. Bu yerda har bir jadval tekshirilib, yetishmayotgan ustun
    `ALTER TABLE ... ADD COLUMN` bilan qo'shiladi.
    """
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    dialect = sync_conn.dialect

    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            # Enum ustun bo'lsa, avval PostgreSQL turini yaratish kerak
            if isinstance(column.type, SAEnum):
                try:
                    column.type.create(sync_conn, checkfirst=True)
                except Exception:
                    pass
            try:
                col_type = column.type.compile(dialect=dialect)
            except Exception:
                log.warning("Ustun turi aniqlanmadi: %s.%s", table.name, column.name)
                continue
            # Yangi ustun har doim NULL bo'la oladigan qilib qo'shiladi —
            # mavjud qatorlarda qiymat yo'qligi uchun.
            sync_conn.execute(
                text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
            )
            log.info("Ustun qo'shildi: %s.%s (%s)", table.name, column.name, col_type)


async def init_db() -> None:
    """Jadvallarni yaratadi va sxemani model bilan moslaydi."""
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_columns)
