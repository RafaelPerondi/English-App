"""
Repositório de dados — substitui o SessionManager em memória.

Todas as operações de banco ficam aqui. O resto do código
chama este módulo em vez de acessar SQLAlchemy diretamente.

Uso:
    from app.database.repository import UserRepository

    async with get_db() as db:
        repo = UserRepository(db)
        user = await repo.get_or_create_user("5547999990001")
        conv = await repo.get_or_create_conversation(user.id)
        await repo.add_message(conv.id, "user", "Hello!")
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Conversation,
    Correction,
    CorrectionError,
    CorrectionTip,
    Message,
    User,
    UserProgress,
)
from config import settings

logger = logging.getLogger(__name__)


class UserRepository:
    """Operações de banco para o fluxo principal do bot."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────
    # USERS
    # ──────────────────────────────────────

    async def get_or_create_user(self, phone: str) -> User:
        """
        Busca usuário pelo telefone.
        Se não existir, cria um novo.
        """
        result = await self.db.execute(
            select(User).where(User.phone == phone)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(phone=phone)
            self.db.add(user)
            await self.db.flush()  # gera o ID sem commitar
            logger.info("Novo usuário criado: %s", phone)

        return user

    async def update_user(
        self,
        user_id: uuid.UUID,
        **kwargs,
    ) -> None:
        """
        Atualiza campos do usuário.
        Exemplo: await repo.update_user(user.id, name="Maria", english_level="A")
        """
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(**kwargs, updated_at=datetime.now(timezone.utc))
        )

    # ──────────────────────────────────────
    # CONVERSATIONS
    # ──────────────────────────────────────

    async def get_active_conversation(self, user_id: uuid.UUID) -> Conversation | None:
        """
        Busca a conversa ativa (não encerrada e não expirada) do usuário.
        Retorna None se não houver conversa ativa.
        """
        timeout = timedelta(minutes=settings.session_timeout_minutes)
        cutoff = datetime.now(timezone.utc) - timeout

        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.state != "ended",
                Conversation.updated_at > cutoff,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_conversation(
        self,
        user_id: uuid.UUID,
        state: str = "new",
    ) -> Conversation:
        """Cria uma nova conversa para o usuário."""
        conv = Conversation(user_id=user_id, state=state)
        self.db.add(conv)
        await self.db.flush()
        logger.info("Nova conversa criada para user_id=%s", user_id)
        return conv

    async def get_or_create_conversation(self, user_id: uuid.UUID) -> Conversation:
        """
        Busca conversa ativa ou cria uma nova.
        Equivalente ao session_manager.get() anterior.
        """
        conv = await self.get_active_conversation(user_id)
        if conv is None:
            conv = await self.create_conversation(user_id)
        return conv

    async def update_conversation(
        self,
        conv_id: uuid.UUID,
        **kwargs,
    ) -> None:
        """
        Atualiza campos da conversa.
        Exemplo: await repo.update_conversation(conv.id, state="chatting", topic="viagens")
        """
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id)
            .values(**kwargs, updated_at=datetime.now(timezone.utc))
        )

    async def end_conversation(self, conv_id: uuid.UUID) -> None:
        """Marca a conversa como encerrada."""
        await self.update_conversation(
            conv_id,
            state="ended",
            ended_at=datetime.now(timezone.utc),
        )

    # ──────────────────────────────────────
    # MESSAGES
    # ──────────────────────────────────────

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        message_type: str = "text",
        audio_transcription: str | None = None,
    ) -> Message:
        """Adiciona uma mensagem à conversa."""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_type=message_type,
            audio_transcription=audio_transcription,
        )
        self.db.add(msg)
        await self.db.flush()

        # Atualiza o updated_at da conversa
        await self.update_conversation(conversation_id)

        return msg

    async def get_conversation_messages(
        self,
        conversation_id: uuid.UUID,
        limit: int = 50,
    ) -> list[Message]:
        """
        Retorna as últimas N mensagens da conversa em ordem cronológica.
        Usado para montar o histórico da OpenAI.
        """
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # volta para ordem cronológica
        return messages

    def messages_to_openai_format(self, messages: list[Message]) -> list[dict]:
        """Converte mensagens do banco para o formato da OpenAI."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    # ──────────────────────────────────────
    # CORRECTIONS
    # ──────────────────────────────────────

    async def save_correction(
        self,
        message_id: uuid.UUID,
        correction_data: dict,
    ) -> Correction:
        """
        Salva a correção completa (com erros e dicas) a partir do JSON da OpenAI.

        correction_data esperado:
        {
            "original": "...",
            "corrected": "...",
            "errors": [{"wrong": "...", "right": "...", "rule": "..."}],
            "tips": ["..."],
            "encouragement": "..."
        }
        """
        correction = Correction(
            message_id=message_id,
            original_text=correction_data.get("original", ""),
            corrected_text=correction_data.get("corrected", ""),
            encouragement=correction_data.get("encouragement"),
        )
        self.db.add(correction)
        await self.db.flush()

        # Salva erros individuais
        for error in correction_data.get("errors", []):
            self.db.add(CorrectionError(
                correction_id=correction.id,
                wrong_text=error.get("wrong", ""),
                right_text=error.get("right", ""),
                rule=error.get("rule"),
            ))

        # Salva dicas
        for tip in correction_data.get("tips", []):
            self.db.add(CorrectionTip(
                correction_id=correction.id,
                tip_text=tip,
            ))

        await self.db.flush()
        return correction

    # ──────────────────────────────────────
    # PROGRESS
    # ──────────────────────────────────────

    async def increment_progress(
        self,
        user_id: uuid.UUID,
        messages: int = 0,
        audio_messages: int = 0,
        errors_found: int = 0,
        new_session: bool = False,
    ) -> None:
        """
        Incrementa contadores de progresso do usuário.
        Cria o registro se não existir.
        """
        result = await self.db.execute(
            select(UserProgress).where(UserProgress.user_id == user_id)
        )
        progress = result.scalar_one_or_none()

        if progress is None:
            progress = UserProgress(user_id=user_id)
            self.db.add(progress)
            await self.db.flush()

        # Incrementa
        if new_session:
            progress.total_sessions += 1
        progress.total_messages += messages
        progress.total_audio_messages += audio_messages
        progress.total_errors_found += errors_found
        progress.last_practice_at = datetime.now(timezone.utc)

        await self.db.flush()
