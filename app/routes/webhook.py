"""
Rotas do webhook — recebe mensagens do WhatsApp via Evolution API
e orquestra o fluxo de conversa do bot professor.

v2.1 — Enquetes interativas para nível de inglês e tema da conversa.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, Request

from config import AUDIO_CACHE_DIR
from app.models.session import ConversationState, EnglishLevel
from app.database.connection import get_db
from app.database.repository import UserRepository
from app.services import openai_service, whatsapp_service, image_service
from app.utils.helpers import generate_id, is_valid_level, clean_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


# ─────────────────────────────────────────────
# Opções das enquetes
# ─────────────────────────────────────────────

LEVEL_OPTIONS = [
    "A - Iniciante (Beginner)",
    "B - Intermediário (Intermediate)",
    "C - Avançado (Advanced)",
]

POLL_LEVEL_MAP = {
    "A - Iniciante (Beginner)": "A",
    "B - Intermediário (Intermediate)": "B",
    "C - Avançado (Advanced)": "C",
}

TOPIC_OPTIONS = [
    "Viagens e Culturas",
    "Tecnologia e Inovação",
    "Filmes e Séries",
    "Esportes e Fitness",
    "Música e Arte",
    "Gastronomia",
    "Negócios e Carreira",
    "Outro (digite o tema)",
]

POLL_TOPIC_MAP = {
    "Viagens e Culturas": "travel and cultures",
    "Tecnologia e Inovação": "technology and innovation",
    "Filmes e Séries": "movies and TV shows",
    "Esportes e Fitness": "sports and fitness",
    "Música e Arte": "music and art",
    "Gastronomia": "food and cooking",
    "Negócios e Carreira": "business and career",
}


# ─────────────────────────────────────────────
# Mensagens do bot (português)
# ─────────────────────────────────────────────

MESSAGES = {
    "welcome": (
        "👋 Olá! Seja muito bem-vindo(a)!\n\n"
        "Sou seu instrutor de inglês e estou aqui para te ajudar a praticar e evoluir. 🎓\n\n"
        "Vamos começar? Me diga, por gentileza, qual é o seu *nome*?"
    ),
    "ask_name": (
        "Por favor, me diga o seu *nome* para que eu possa te chamar corretamente. 😊"
    ),
    "ask_level": (
        "É um grande prazer conhecê-lo, {name}! 😊\n\n"
        "Para que eu possa personalizar nossas aulas, selecione seu nível na enquete abaixo:"
    ),
    "invalid_level": (
        "Ops! Por favor, selecione uma opção na enquete acima. 😊"
    ),
    "ask_topic": (
        "Excelente! Seu nível foi registrado como *{level}* ({description}). ✅\n\n"
        "Agora escolha um tema para conversarmos em inglês:"
    ),
    "starting": (
        "Excelente! Prepararei uma conversa cuidadosamente elaborada sobre *{topic}* para você. 🎯\n\n"
        "Você poderá responder em inglês, seja por *áudio* 🎤 ou por *texto* ✍️."
    ),
    "processing": "🔄 Um momento, estou preparando seu feedback...",
    "error": "😅 Ops! Algo deu errado. Tente novamente em alguns segundos.",
    "reset": "🔄 Sessão resetada! Vamos começar de novo.\n\nQual é o seu *nome*?",
}


# ─────────────────────────────────────────────
# Webhook endpoint
# ─────────────────────────────────────────────

@router.post("/messages")
async def handle_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        logger.error("Payload inválido recebido no webhook")
        return {"status": "error", "message": "invalid payload"}

    event = body.get("event")
    if event != "messages.upsert":
        return {"status": "ignored", "event": event}

    data = body.get("data", {})

    if data.get("key", {}).get("fromMe", False):
        return {"status": "ignored", "reason": "own message"}

    remote_jid = data.get("key", {}).get("remoteJid", "")
    sender_pn = data.get("key", {}).get("senderPn", "")
    if "@lid" in remote_jid and sender_pn:
        phone = sender_pn.replace("@s.whatsapp.net", "")
    else:
        phone = remote_jid.replace("@s.whatsapp.net", "")
    message_type = data.get("messageType", "")
    message_id = data.get("key", {}).get("id", "")

    if not phone:
        return {"status": "error", "message": "no phone number"}

    logger.info("Mensagem recebida de %s | Tipo: %s", phone, message_type)

    text = _extract_text(data)
    poll_response = _extract_poll_response(data)
    is_audio = message_type in ("audioMessage", "pttMessage")

    # Ignora eventos de enquete enviada pelo bot (pollCreationMessage)
    if message_type == "pollCreationMessage":
        return {"status": "ignored", "reason": "poll creation"}

    # Comando especial: reset
    if text and text.strip().lower() in ("/reset", "/reiniciar", "/novo"):
        async with get_db() as db:
            repo = UserRepository(db)
            user = await repo.get_or_create_user(phone)
            conv = await repo.get_active_conversation(user.id)
            if conv:
                await repo.end_conversation(conv.id)
            await repo.create_conversation(user.id, state="waiting_name")
        await whatsapp_service.send_text(phone, MESSAGES["reset"])
        return {"status": "ok"}

    try:
        await _process_message(phone, text, poll_response, is_audio, message_id, data)
    except Exception as e:
        logger.exception("Erro ao processar mensagem de %s: %s", phone, e)
        await whatsapp_service.send_text(phone, MESSAGES["error"])

    return {"status": "ok"}


# ─────────────────────────────────────────────
# Processamento principal
# ─────────────────────────────────────────────

async def _process_message(
    phone: str,
    text: str | None,
    poll_response: str | None,
    is_audio: bool,
    message_id: str,
    raw_data: dict,
) -> None:
    async with get_db() as db:
        repo = UserRepository(db)
        user = await repo.get_or_create_user(phone)
        conv = await repo.get_or_create_conversation(user.id)

        match conv.state:
            case "new":
                await _handle_new(phone, user, conv, repo)
            case "waiting_name":
                await _handle_waiting_name(phone, text, user, conv, repo)
            case "waiting_level":
                await _handle_waiting_level(phone, text, poll_response, user, conv, repo)
            case "waiting_topic":
                await _handle_waiting_topic(phone, text, poll_response, user, conv, repo)
            case "chatting":
                await _handle_chatting(
                    phone, text, is_audio, message_id, raw_data,
                    user, conv, repo,
                )


# ─────────────────────────────────────────────
# Handlers de cada estado
# ─────────────────────────────────────────────

async def _handle_new(phone, user, conv, repo: UserRepository):
    await repo.update_conversation(conv.id, state="waiting_name")
    await repo.increment_progress(user.id, new_session=True)
    await whatsapp_service.send_text(phone, MESSAGES["welcome"])


async def _handle_waiting_name(phone, text, user, conv, repo: UserRepository):
    if not text:
        await whatsapp_service.send_text(phone, MESSAGES["ask_name"])
        return

    name = clean_text(text)
    await repo.update_user(user.id, name=name)
    await repo.update_conversation(conv.id, state="waiting_level")

    await whatsapp_service.send_text(
        phone, MESSAGES["ask_level"].format(name=name),
    )
    await whatsapp_service.send_poll(
        phone, "📚 Qual é o seu nível de inglês?", LEVEL_OPTIONS,
    )


async def _handle_waiting_level(phone, text, poll_response, user, conv, repo: UserRepository):
    level_key = None

    # Tenta da enquete primeiro
    if poll_response and poll_response in POLL_LEVEL_MAP:
        level_key = POLL_LEVEL_MAP[poll_response]
        logger.info("Nível via enquete: %s -> %s", poll_response, level_key)
    # Fallback: texto A/B/C
    elif text and is_valid_level(text):
        level_key = text.strip().upper()

    if not level_key:
        await whatsapp_service.send_text(phone, MESSAGES["invalid_level"])
        await whatsapp_service.send_poll(
            phone, "📚 Qual é o seu nível de inglês?", LEVEL_OPTIONS,
        )
        return

    level_enum = EnglishLevel(level_key)
    await repo.update_user(user.id, english_level=level_key)
    await repo.update_conversation(conv.id, state="waiting_topic", english_level=level_key)

    await whatsapp_service.send_text(
        phone, MESSAGES["ask_topic"].format(
            level=level_enum.value, description=level_enum.description,
        ),
    )
    await whatsapp_service.send_poll(
        phone, "🎯 Escolha um tema para conversar:", TOPIC_OPTIONS,
    )


async def _handle_waiting_topic(phone, text, poll_response, user, conv, repo: UserRepository):
    topic = None

    # Tenta da enquete primeiro
    if poll_response and poll_response in POLL_TOPIC_MAP:
        topic = POLL_TOPIC_MAP[poll_response]
        logger.info("Tema via enquete: %s -> %s", poll_response, topic)
    elif poll_response and poll_response == "Outro (digite o tema)":
        await whatsapp_service.send_text(
            phone, "Legal! Digite o tema que você quer conversar em inglês: 😊"
        )
        return
    # Fallback: texto livre
    elif text:
        topic = clean_text(text)

    if not topic:
        await whatsapp_service.send_text(
            phone, "Por favor, escolha um tema na enquete ou digite o tema que preferir! 😊"
        )
        await whatsapp_service.send_poll(
            phone, "🎯 Escolha um tema para conversar:", TOPIC_OPTIONS,
        )
        return

    await repo.update_user(user.id, preferred_topic=topic)
    await repo.update_conversation(conv.id, state="chatting", topic=topic)

    await whatsapp_service.send_text(
        phone, MESSAGES["starting"].format(topic=topic),
    )

    session_data = _build_session_data(user.name, conv.english_level, topic, [])
    first_message = await openai_service.generate_first_message(session_data)
    await repo.add_message(conv.id, "assistant", first_message)
    await whatsapp_service.send_text(phone, f"🎓 _{first_message}_")


async def _handle_chatting(
    phone, text, is_audio, message_id, raw_data,
    user, conv, repo: UserRepository,
):
    if is_audio:
        await _handle_audio_response(phone, message_id, raw_data, user, conv, repo)
    elif text:
        await _handle_text_response(phone, text, user, conv, repo)
    else:
        await whatsapp_service.send_text(
            phone, "Pode responder com *áudio* 🎤 ou *texto* ✍️!"
        )


async def _handle_audio_response(
    phone, message_id, raw_data, user, conv, repo: UserRepository,
):
    await whatsapp_service.send_text(phone, MESSAGES["processing"])

    audio_path = await _download_audio(message_id, raw_data)
    if not audio_path:
        await whatsapp_service.send_text(
            phone, "😅 Não consegui processar seu áudio. Tente novamente!"
        )
        return

    transcription = await openai_service.transcribe_audio(audio_path)
    if not transcription:
        await whatsapp_service.send_text(
            phone, "😅 Não consegui entender o áudio. Tente novamente!"
        )
        return

    user_msg = await repo.add_message(
        conv.id, "user", transcription,
        message_type="audio", audio_transcription=transcription,
    )
    await repo.increment_progress(user.id, messages=1, audio_messages=1)

    correction = await openai_service.correct_text(transcription)
    num_errors = len(correction.get("errors", []))
    await repo.save_correction(user_msg.id, correction)
    await repo.increment_progress(user.id, errors_found=num_errors)

    image_id = generate_id()
    image_path = image_service.generate_feedback_image(correction, image_id)
    await whatsapp_service.send_image(phone, image_path)

    tips = correction.get("tips", [])
    if tips:
        tips_text = "\n".join(f"💡 {tip}" for tip in tips)
        await whatsapp_service.send_text(phone, f"📚 *Dicas:*\n\n{tips_text}")

    messages = await repo.get_conversation_messages(conv.id, limit=30)
    openai_history = repo.messages_to_openai_format(messages)
    session_data = _build_session_data(user.name, conv.english_level, conv.topic, openai_history)

    reply = await openai_service.chat_response(session_data, transcription)
    await repo.add_message(conv.id, "assistant", reply)

    audio_id = generate_id()
    reply_audio = await openai_service.text_to_speech(reply, audio_id)
    await whatsapp_service.send_audio(phone, reply_audio)
    await whatsapp_service.send_text(phone, f"📝 _{reply}_")


async def _handle_text_response(phone, text, user, conv, repo: UserRepository):
    user_msg = await repo.add_message(conv.id, "user", text)
    await repo.increment_progress(user.id, messages=1)

    correction = await openai_service.correct_text(text)
    num_errors = len(correction.get("errors", []))
    await repo.save_correction(user_msg.id, correction)
    await repo.increment_progress(user.id, errors_found=num_errors)

    errors = correction.get("errors", [])
    if errors:
        correction_lines = ["📝 *Correction:*\n"]
        for error in errors:
            wrong = error.get("wrong", "")
            right = error.get("right", "")
            rule = error.get("rule", "")
            correction_lines.append(f"  ✗ ~{wrong}~  →  *{right}*")
            if rule:
                correction_lines.append(f"     _{rule}_")
        correction_lines.append(f"\n✅ *Better version:*\n_{correction.get('corrected', text)}_")
        tips = correction.get("tips", [])
        if tips:
            correction_lines.append("")
            for tip in tips:
                correction_lines.append(f"💡 {tip}")
        encouragement = correction.get("encouragement", "")
        if encouragement:
            correction_lines.append(f"\n💪 {encouragement}")
        await whatsapp_service.send_text(phone, "\n".join(correction_lines))
    else:
        encouragement = correction.get("encouragement", "Perfect! No errors!")
        await whatsapp_service.send_text(phone, f"✅ {encouragement}")

    messages = await repo.get_conversation_messages(conv.id, limit=30)
    openai_history = repo.messages_to_openai_format(messages)
    session_data = _build_session_data(user.name, conv.english_level, conv.topic, openai_history)

    reply = await openai_service.chat_response(session_data, text)
    await repo.add_message(conv.id, "assistant", reply)
    await whatsapp_service.send_text(phone, f"🎓 _{reply}_")


# ─────────────────────────────────────────────
# Funções auxiliares
# ─────────────────────────────────────────────

def _build_session_data(name, english_level, topic, chat_history):
    level = None
    if english_level:
        try:
            level = EnglishLevel(english_level)
        except ValueError:
            level = EnglishLevel.A
    return {
        "name": name or "Student",
        "level": level or EnglishLevel.A,
        "topic": topic or "general conversation",
        "chat_history": chat_history,
    }


def _extract_text(data: dict) -> str | None:
    message = data.get("message", {})
    if "conversation" in message:
        return message["conversation"]
    if "extendedTextMessage" in message:
        return message["extendedTextMessage"].get("text")
    return None


def _extract_poll_response(data: dict) -> str | None:
    """
    Extrai a resposta de uma enquete.
    A Evolution API envia o voto em diferentes formatos dependendo da versão.
    """
    message = data.get("message", {})
    msg_type = data.get("messageType", "")

    # Formato: pollUpdateMessage
    poll_update = message.get("pollUpdateMessage", {})
    if poll_update:
        vote = poll_update.get("vote", {})
        if isinstance(vote, dict):
            options = vote.get("selectedOptions", [])
            if options:
                return options[0] if isinstance(options[0], str) else options[0].get("name", "")
        elif isinstance(vote, list) and vote:
            return vote[0] if isinstance(vote[0], str) else str(vote[0])

    # Formato: pollResponseMessage
    poll_resp = message.get("pollResponseMessage", {})
    if poll_resp:
        selected = poll_resp.get("selectedOptions", [])
        if selected:
            return selected[0] if isinstance(selected[0], str) else selected[0].get("name", "")

    # Formato: Evolution API v2 decodifica e envia como body
    if msg_type in ("pollUpdateMessage", "pollResponseMessage"):
        body = data.get("body", "")
        if body:
            return body

    return None


async def _download_audio(message_id: str, raw_data: dict) -> Path | None:
    try:
        audio_path = AUDIO_CACHE_DIR / f"{generate_id()}.ogg"
        try:
            media_data = await whatsapp_service.get_media_base64(message_id)
            if media_data and "base64" in media_data:
                audio_bytes = base64.b64decode(media_data["base64"])
                audio_path.write_bytes(audio_bytes)
                logger.info("Áudio baixado via base64: %s", audio_path)
                return audio_path
        except Exception as e:
            logger.warning("Falha ao obter áudio via base64: %s", e)

        message = raw_data.get("message", {})
        audio_msg = message.get("audioMessage", {}) or message.get("pttMessage", {})
        media_url = audio_msg.get("url")
        if media_url:
            await whatsapp_service.download_media(media_url, audio_path)
            return audio_path

        logger.error("Nenhuma fonte de áudio disponível")
        return None
    except Exception as e:
        logger.exception("Erro ao baixar áudio: %s", e)
        return None
