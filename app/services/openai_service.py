"""
Serviço de integração com a OpenAI.
Responsável por: chat (GPT), transcrição (Whisper) e geração de áudio (TTS).
"""

from __future__ import annotations

import logging
from pathlib import Path

from openai import AsyncOpenAI

from config import settings, AUDIO_CACHE_DIR
from app.models.session import EnglishLevel, Session

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)


# ─────────────────────────────────────────────
# Prompts do sistema
# ─────────────────────────────────────────────

def _build_system_prompt(session: Session) -> str:
    """Constrói o prompt do sistema baseado no perfil do aluno."""
    level = session.level
    level_instructions = {
        EnglishLevel.A: (
            "The student is a BEGINNER (A1-A2). "
            "Use very simple vocabulary and short sentences. "
            "Speak slowly and clearly. Use present tense mostly. "
            "Be very encouraging and patient."
        ),
        EnglishLevel.B: (
            "The student is INTERMEDIATE (B1-B2). "
            "Use moderate vocabulary with some idioms. "
            "Mix tenses naturally. Challenge them a bit "
            "but keep it accessible."
        ),
        EnglishLevel.C: (
            "The student is ADVANCED (C1-C2). "
            "Use rich vocabulary, idioms, phrasal verbs, and complex structures. "
            "Speak naturally as you would to a native speaker. "
            "Challenge them with nuanced topics."
        ),
    }

    return f"""You are a friendly and encouraging English teacher having a conversation \
with a student named {session.name}.

{level_instructions.get(level, level_instructions[EnglishLevel.A])}

The conversation topic is: "{session.topic}".

RULES:
- Always respond IN ENGLISH.
- Keep responses conversational, 2-4 sentences max.
- Ask follow-up questions to keep the conversation going.
- Be warm and encouraging.
- Do NOT correct errors in the conversation flow — corrections are handled separately.
- Stay on topic but allow natural tangents."""


def _build_correction_prompt() -> str:
    """Prompt para corrigir o texto do aluno."""
    return """You are an English teacher analyzing a student's message.

Respond in this EXACT JSON format (no markdown, no backticks):
{
    "original": "the student's original text",
    "corrected": "the corrected version",
    "errors": [
        {"wrong": "error word/phrase", "right": "correction", "rule": "brief grammar rule"}
    ],
    "tips": ["practical tip 1", "practical tip 2"],
    "encouragement": "a short encouraging message"
}

If the text has no errors, set "errors" to an empty list and still provide tips.
Always provide at least 1 tip. Write all tips in Brazilian Portuguese. Provide the response and nothing else."""


def _build_first_message_prompt(session: Session) -> str:
    """Prompt para a primeira mensagem sobre o tema escolhido."""
    return f"""Start a conversation about "{session.topic}" with the student.
Introduce the topic in a fun and engaging way.
Ask an opening question to get them talking.
Keep it to 2-3 sentences. Be friendly and enthusiastic."""


# ─────────────────────────────────────────────
# Chat (GPT)
# ─────────────────────────────────────────────

async def chat_response(session: Session, user_message: str) -> str:
    """
    Gera resposta de conversa do professor.
    Mantém o contexto usando o histórico da sessão.
    """
    system_prompt = _build_system_prompt(session)
    messages = [
        {"role": "system", "content": system_prompt},
        *session.get_openai_messages(),
        {"role": "user", "content": user_message},
    ]

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.8,
        max_tokens=300,
    )

    reply = response.choices[0].message.content.strip()

    # Salva no histórico
    session.add_message("user", user_message)
    session.add_message("assistant", reply)

    return reply


async def generate_first_message(session: Session) -> str:
    """Gera a primeira mensagem do professor sobre o tema escolhido."""
    system_prompt = _build_system_prompt(session)
    user_prompt = _build_first_message_prompt(session)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=300,
    )

    reply = response.choices[0].message.content.strip()
    session.add_message("assistant", reply)
    return reply


async def correct_text(student_text: str) -> dict:
    """
    Analisa e corrige o texto do aluno.
    Retorna dict com: original, corrected, errors, tips, encouragement.
    """
    import json

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _build_correction_prompt()},
            {"role": "user", "content": student_text},
        ],
        temperature=0.3,
        max_tokens=500,
    )

    raw = response.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Falha ao parsear JSON da correção: %s", raw)
        return {
            "original": student_text,
            "corrected": student_text,
            "errors": [],
            "tips": ["Keep practicing! You're doing great!"],
            "encouragement": "Great effort! Keep going!",
        }


# ─────────────────────────────────────────────
# Transcrição (Whisper)
# ─────────────────────────────────────────────

async def transcribe_audio(audio_path: Path) -> str:
    """Transcreve um arquivo de áudio usando Whisper."""
    logger.info("Transcrevendo áudio: %s", audio_path)

    with open(audio_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
        )

    text = transcription.text.strip()
    logger.info("Transcrição: %s", text)
    return text


# ─────────────────────────────────────────────
# Text-to-Speech (TTS)
# ─────────────────────────────────────────────

async def text_to_speech(text: str, filename: str) -> Path:
    """
    Converte texto em áudio MP3.
    Retorna o caminho do arquivo gerado.
    """
    output_path = AUDIO_CACHE_DIR / f"{filename}.mp3"

    response = await client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=text,
        response_format="mp3",
    )

    response.stream_to_file(str(output_path))
    logger.info("Áudio gerado: %s", output_path)
    return output_path
