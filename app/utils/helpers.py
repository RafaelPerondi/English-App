"""
Funções utilitárias do bot.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_id() -> str:
    """Gera um ID único curto."""
    return uuid.uuid4().hex[:12]


def sanitize_phone(phone: str) -> str:
    """Remove caracteres não numéricos de um número de telefone."""
    return re.sub(r"\D", "", phone)


def is_valid_level(text: str) -> bool:
    """Verifica se o texto é um nível válido (A, B ou C)."""
    return text.strip().upper() in {"A", "B", "C"}


def clean_text(text: str) -> str:
    """Limpa texto removendo espaços extras."""
    return " ".join(text.split()).strip()


def setup_logging() -> None:
    """Configura o logging da aplicação."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("bot.log", encoding="utf-8"),
        ],
    )

    # Reduz verbosidade de libs externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
