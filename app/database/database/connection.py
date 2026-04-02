"""
Conexão com o PostgreSQL usando SQLAlchemy 2.0 + asyncpg.

Uso:
    from app.database.connection import get_db, init_db, close_db

    # No lifespan do FastAPI:
    async with lifespan(app):
        await init_db()   # cria pool
        yield
        await close_db()  # fecha pool

    # Nas rotas/services:
    async with get_db() as db:
        result = await db.execute(select(User))
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

logger = logging.getLogger(__name__)

# Engine e session factory — inicializados em init_db()
_engine = None
_session_factory = None


async def init_db() -> None:
    """Cria o engine e a session factory. Chamar uma vez no startup."""
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.database_url,
        echo=False,            # True para debug SQL
        pool_size=10,          # conexões no pool
        max_overflow=20,       # conexões extras em pico
        pool_pre_ping=True,    # verifica conexão antes de usar
        pool_recycle=3600,     # recicla conexões a cada 1h
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,  # evita lazy loads inesperados
    )

    logger.info("✅ Conexão com banco de dados inicializada")


async def close_db() -> None:
    """Fecha o engine e o pool de conexões. Chamar no shutdown."""
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("🛑 Conexão com banco de dados encerrada")


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager que fornece uma sessão do banco.
    Faz commit automático se não houver exceção, rollback se houver.

    Uso:
        async with get_db() as db:
            user = await db.execute(select(User).where(...))
    """
    if _session_factory is None:
        raise RuntimeError("Banco de dados não inicializado. Chame init_db() primeiro.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
