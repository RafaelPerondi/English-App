"""
Gerenciador de sessões em memória.

MIGRAÇÃO FUTURA PARA BANCO DE DADOS:
  1. Crie uma classe SessionRepository com a mesma interface (get, create, delete)
  2. Implemente usando SQLAlchemy, Tortoise ORM, ou similar
  3. Substitua a instância `session_manager` por uma que use o repositório
  4. O resto do código não precisa mudar
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config import settings
from app.models.session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Armazena sessões em memória (dict).
    Chave: número de telefone do cliente.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, phone: str) -> Session:
        """
        Retorna a sessão do telefone.
        Cria uma nova se não existir ou se expirou.
        """
        session = self._sessions.get(phone)

        if session is None:
            return self.create(phone)

        # Verifica expiração
        timeout = timedelta(minutes=settings.session_timeout_minutes)
        if datetime.now() - session.updated_at > timeout:
            logger.info("Sessão expirada para %s. Criando nova.", phone)
            return self.create(phone)

        return session

    def create(self, phone: str) -> Session:
        """Cria uma nova sessão para o telefone."""
        session = Session(phone=phone)
        self._sessions[phone] = session
        logger.info("Nova sessão criada para %s", phone)
        return session

    def delete(self, phone: str) -> None:
        """Remove a sessão do telefone."""
        self._sessions.pop(phone, None)
        logger.info("Sessão removida para %s", phone)

    def list_active(self) -> list[Session]:
        """Lista todas as sessões ativas (para debug/admin)."""
        return list(self._sessions.values())

    def cleanup_expired(self) -> int:
        """Remove sessões expiradas. Retorna quantas foram removidas."""
        timeout = timedelta(minutes=settings.session_timeout_minutes)
        now = datetime.now()
        expired = [
            phone
            for phone, session in self._sessions.items()
            if now - session.updated_at > timeout
        ]
        for phone in expired:
            del self._sessions[phone]

        if expired:
            logger.info("Limpeza: %d sessões expiradas removidas.", len(expired))
        return len(expired)


# Instância global — substituir por injeção de dependência no futuro
session_manager = SessionManager()
