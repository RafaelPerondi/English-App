"""
Configuração do servidor FastAPI.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.webhook import router as webhook_router
from app.services import whatsapp_service
from app.database.connection import init_db, close_db  # ← NOVO

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia startup e shutdown da aplicação."""
    logger.info("🚀 English Teacher Bot iniciando...")

    # Inicializa conexão com o banco  ← NOVO
    await init_db()
    logger.info("🗄️  Banco de dados conectado")

    logger.info("📡 Webhook pronto em /webhook/messages")
    yield
    logger.info("🛑 Encerrando bot...")
    await whatsapp_service.close()
    await close_db()  # ← NOVO
    logger.info("✅ Bot encerrado com sucesso.")


def create_app() -> FastAPI:
    """Factory do FastAPI — facilita testes e configuração."""
    app = FastAPI(
        title="English Teacher Bot",
        description="Bot professor de inglês via WhatsApp",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS (útil se adicionar painel admin no futuro)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rotas
    app.include_router(webhook_router)

    # Health check  ← ATUALIZADO (sem session_manager)
    @app.get("/health")
    async def health():
        return {
            "status": "online",
            "database": "connected",
        }

    # Info
    @app.get("/")
    async def root():
        return {
            "name": "English Teacher Bot",
            "version": "2.0.0",
            "docs": "/docs",
        }

    return app
