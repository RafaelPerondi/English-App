"""
Modelos de dados para sessões de conversa.

Preparado para migração futura para banco de dados:
- Trocar o SessionManager em-memória por um repositório com SQLAlchemy/Tortoise
- Os modelos Pydantic servem como DTOs e podem virar modelos ORM facilmente
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ConversationState(str, enum.Enum):
    """Estados possíveis da conversa com o aluno."""

    NEW = "new"                    # acabou de chegar, ainda não recebeu boas-vindas
    WAITING_NAME = "waiting_name"  # boas-vindas enviadas, esperando o nome
    WAITING_LEVEL = "waiting_level"
    WAITING_TOPIC = "waiting_topic"
    CHATTING = "chatting"


class EnglishLevel(str, enum.Enum):
    """Níveis de inglês suportados."""

    A = "A"  # Iniciante
    B = "B"  # Intermediário
    C = "C"  # Avançado

    @property
    def description(self) -> str:
        return {
            "A": "Beginner",
            "B": "Intermediate",
            "C": "Advanced",
        }[self.value]

    @property
    def cefr(self) -> str:
        return {
            "A": "A1-A2",
            "B": "B1-B2",
            "C": "C1-C2",
        }[self.value]


class ChatMessage(BaseModel):
    """Uma mensagem no histórico da conversa."""

    role: str  # "user" ou "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Session(BaseModel):
    """
    Sessão de um aluno.
    Contém todo o estado necessário para a conversa.
    """

    phone: str
    name: Optional[str] = None
    level: Optional[EnglishLevel] = None
    topic: Optional[str] = None
    state: ConversationState = ConversationState.NEW
    chat_history: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_message(self, role: str, content: str) -> None:
        """Adiciona mensagem ao histórico e atualiza timestamp."""
        self.chat_history.append(ChatMessage(role=role, content=content))
        self.updated_at = datetime.now()

    def get_openai_messages(self) -> list[dict]:
        """Retorna histórico no formato esperado pela API da OpenAI."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.chat_history
        ]

    def reset(self) -> None:
        """Reseta a sessão para o estado inicial."""
        self.name = None
        self.level = None
        self.topic = None
        self.state = ConversationState.NEW
        self.chat_history.clear()
        self.updated_at = datetime.now()
