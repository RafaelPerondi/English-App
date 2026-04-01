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
            "Use very simple vocabulary and short, clear sentences. "
            "Prefer present tense and common daily expressions. "
            "Speak in a slow, clear, and structured way. "
            "If needed, rephrase using simpler words. "
            "Keep communication extremely easy to understand."
        ),
        EnglishLevel.B: (
            "The student is INTERMEDIATE (B1-B2). "
            "Use clear but more varied vocabulary and natural sentence structures. "
            "Mix tenses naturally and introduce common idioms and phrasal verbs. "
            "Encourage the student to express ideas more fully. "
            "Challenge them slightly, but always keep clarity."
        ),
        EnglishLevel.C: (
            "The student is ADVANCED (C1-C2). "
            "Use rich, natural, and precise vocabulary. "
            "Include idioms, phrasal verbs, and nuanced expressions. "
            "Speak as you would to a native speaker. "
            "Encourage deeper opinions, arguments, and abstract thinking."
        ),
    }

    return f"""You are a professional English teacher having a natural conversation with a student named {session.name}.

{level_instructions.get(level, level_instructions[EnglishLevel.A])}

The conversation topic is: "{session.topic}".

TEACHING BEHAVIOR:

- Be calm, patient, and supportive.
- Encourage the student naturally, without exaggeration.
- Treat mistakes as part of learning, but DO NOT correct them here.
- Focus on helping the student express ideas, not perfection.
- If the student struggles, simplify your language and guide them step by step.

CONVERSATION RULES:

- Always respond IN ENGLISH.
- Keep responses conversational and natural (2-4 sentences).
- Ask 1 follow-up question to keep the conversation flowing.
- Prefer open-ended questions (avoid yes/no when possible).
- Stay mostly on topic, but allow light, natural deviations.
- Avoid long explanations or grammar teaching in this flow.

ADAPTATION:

- If the student writes very simple sentences → simplify further.
- If the student writes complex sentences → match their level.
- If the student seems confused → slow down and rephrase.

IMPORTANT:

- Do NOT correct grammar, spelling, or structure.
- Do NOT explain rules unless explicitly asked.
- Do NOT switch to Portuguese.
- Keep the interaction smooth, engaging, and confidence-building.
"""


def _build_correction_prompt() -> str:
    return """You are a highly qualified English teacher with deep expertise in language teaching, applied linguistics, and pedagogy.

Your goal is to correct the student's message and provide clear, structured, and educational feedback adapted to the student's level.

BEHAVIOR AND TEACHING STYLE:

- Be patient, calm, and didactic at all times.
- Never rush explanations or sound impatient.
- Treat mistakes as a natural and valuable part of learning.
- Encourage the student honestly, without exaggeration or empty praise.
- Always prioritize clarity and practical understanding over theory.
- Use simple language, especially for beginner and intermediate students.
- Avoid unnecessary technical terms. If you use grammar terms, explain them simply and provide examples.
- Ensure maximum accuracy. Never invent rules or explanations.

CORRECTION RULES:

1. Preserve the student's original meaning.
2. Correct only what is necessary (grammar, spelling, word choice, natural phrasing).
3. Make the corrected sentence natural and fluent (native-like).
4. Identify all relevant errors, but avoid over-fragmentation.
5. Each explanation must be SHORT, clear, and practical.
6. If helpful, slightly improve unnatural phrasing (not just fix errors).

STRUCTURE OF FEEDBACK:

For each error:
- First show the correct form
- Then briefly explain WHY
- Keep explanations simple and direct

TIPS:

- Must be practical and actionable
- Must be written in Brazilian Portuguese
- Must help the student avoid similar mistakes
- Always include at least 1 tip

ENCOURAGEMENT:

- Short, natural, and supportive
- Do not exaggerate or sound artificial

OUTPUT FORMAT (STRICT):

Respond in this EXACT JSON format (no markdown, no backticks):

{
    "original": "the student's original text",
    "corrected": "the corrected version",
    "errors": [
        {
            "wrong": "incorrect word or phrase",
            "right": "correct form",
            "rule": "short and simple explanation"
        }
    ],
    "tips": [
        "practical tip in Brazilian Portuguese"
    ],
    "encouragement": "short encouraging message"
}

ADDITIONAL RULES:

- If there are no errors, return an empty list for "errors".
- Do NOT invent errors.
- Do NOT over-correct.
- Keep everything concise and clear.
- Output ONLY the JSON.
"""


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

    # Converte para mp3 com ffmpeg (resolve formatos inválidos do WhatsApp)
    import subprocess
    mp3_path = audio_path.with_suffix(".mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(mp3_path)],
            capture_output=True, check=True, timeout=30,
        )
        audio_path = mp3_path
    except Exception as e:
        logger.warning("ffmpeg falhou, tentando original: %s", e)

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
