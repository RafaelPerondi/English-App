"""
Rotas do webhook — recebe mensagens do WhatsApp via Evolution API
e orquestra o fluxo de conversa do bot professor.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, Request

from config import AUDIO_CACHE_DIR
from app.models.session import ConversationState, EnglishLevel
from app.services.session_manager import session_manager
from app.services import openai_service, whatsapp_service, image_service
from app.utils.helpers import generate_id, is_valid_level, clean_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


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
        "Para que eu possa personalizar nossas aulas de inglês de maneira ideal, poderia gentilmente informar seu nível de proficiência?\n\n"
        "*A* — Iniciante (Beginner)\n"
        "*B* — Intermediário (Intermediate)\n"
        "*C* — Avançado (Advanced)\n\n"
        "Agradeço se puder responder com *A*, *B* ou *C*."
    ),
    "invalid_level": (
        "Ops! Por favor, responda apenas com *A*, *B* ou *C*.\n\n"
        "*A* — Iniciante\n"
        "*B* — Intermediário\n"
        "*C* — Avançado"
    ),
    "ask_topic": (
        "Excelente! Seu nível foi registrado como *{level}* ({description}). ✅\n\n"
        "Para que nossas conversas em inglês sejam mais proveitosas, poderia informar os temas que despertam maior interesse em você? 🤔\n\n"
        "Por exemplo: literatura, viagens culturais, gastronomia internacional, inovação tecnológica, cinema clássico, artes ou música."
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
    """
    Endpoint principal que recebe todas as mensagens do WhatsApp.
    A Evolution API envia eventos aqui via POST.
    """
    try:
        body = await request.json()
    except Exception:
        logger.error("Payload inválido recebido no webhook")
        return {"status": "error", "message": "invalid payload"}

    # Ignora eventos que não são mensagens
    event = body.get("event")
    if event != "messages.upsert":
        return {"status": "ignored", "event": event}

    data = body.get("data", {})

    # Ignora mensagens enviadas pelo próprio bot
    if data.get("key", {}).get("fromMe", False):
        return {"status": "ignored", "reason": "own message"}

    # Extrai informações da mensagem
    # Usa senderPn (número real) quando remoteJid é @lid (formato novo do WhatsApp)
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

    # Extrai texto da mensagem
    text = _extract_text(data)
    is_audio = message_type in ("audioMessage", "pttMessage")

    # Comando especial: reset
    if text and text.strip().lower() in ("/reset", "/reiniciar", "/novo"):
        session = session_manager.get(phone)
        session.reset()
        await whatsapp_service.send_text(phone, MESSAGES["reset"])
        return {"status": "ok"}

    # Processa a mensagem
    try:
        await _process_message(phone, text, is_audio, message_id, data)
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
    is_audio: bool,
    message_id: str,
    raw_data: dict,
) -> None:
    """Orquestra o fluxo de conversa baseado no estado da sessão."""
    session = session_manager.get(phone)

    match session.state:
        case ConversationState.NEW:
            await _handle_new(phone, text, session)

        case ConversationState.WAITING_NAME:
            await _handle_waiting_name(phone, text, session)

        case ConversationState.WAITING_LEVEL:
            await _handle_waiting_level(phone, text, session)

        case ConversationState.WAITING_TOPIC:
            await _handle_waiting_topic(phone, text, session)

        case ConversationState.CHATTING:
            await _handle_chatting(phone, text, is_audio, message_id, raw_data, session)


# ─────────────────────────────────────────────
# Handlers de cada estado
# ─────────────────────────────────────────────

async def _handle_new(phone: str, text: str | None, session) -> None:
    """Estado: primeiro contato — envia boas-vindas e pergunta o nome."""
    # Qualquer mensagem (texto, áudio, imagem) dispara as boas-vindas
    session.state = ConversationState.WAITING_NAME
    await whatsapp_service.send_text(phone, MESSAGES["welcome"])


async def _handle_waiting_name(phone: str, text: str | None, session) -> None:
    """Estado: esperando o nome do aluno (boas-vindas já foram enviadas)."""
    if not text:
        # Se mandou áudio/imagem em vez de texto, pede de novo
        await whatsapp_service.send_text(phone, MESSAGES["ask_name"])
        return

    session.name = clean_text(text)
    session.state = ConversationState.WAITING_LEVEL

    await whatsapp_service.send_text(
        phone,
        MESSAGES["ask_level"].format(name=session.name),
    )


async def _handle_waiting_level(phone: str, text: str | None, session) -> None:
    """Estado: esperando o nível de inglês."""
    if not text or not is_valid_level(text):
        await whatsapp_service.send_text(phone, MESSAGES["invalid_level"])
        return

    level_key = text.strip().upper()
    session.level = EnglishLevel(level_key)
    session.state = ConversationState.WAITING_TOPIC

    await whatsapp_service.send_text(
        phone,
        MESSAGES["ask_topic"].format(
            level=session.level.value,
            description=session.level.description,
        ),
    )


async def _handle_waiting_topic(phone: str, text: str | None, session) -> None:
    """Estado: esperando o tema da conversa."""
    if not text:
        await whatsapp_service.send_text(
            phone,
            "Por favor, me diga um *tema* para conversarmos em inglês! 😊"
        )
        return

    session.topic = clean_text(text)
    session.state = ConversationState.CHATTING

    # Avisa que está preparando
    await whatsapp_service.send_text(
        phone,
        MESSAGES["starting"].format(topic=session.topic),
    )

    # Gera primeira mensagem do professor
    first_message = await openai_service.generate_first_message(session)

    # Envia apenas como texto (áudio só quando o aluno mandar áudio)
    await whatsapp_service.send_text(phone, f"🎓 _{first_message}_")


async def _handle_chatting(
    phone: str,
    text: str | None,
    is_audio: bool,
    message_id: str,
    raw_data: dict,
    session,
) -> None:
    """Estado: conversa ativa — processa áudio ou texto do aluno."""

    if is_audio:
        await _handle_audio_response(phone, message_id, raw_data, session)
    elif text:
        await _handle_text_response(phone, text, session)
    else:
        await whatsapp_service.send_text(
            phone,
            "Pode responder com *áudio* 🎤 ou *texto* ✍️!"
        )


async def _handle_audio_response(
    phone: str, message_id: str, raw_data: dict, session
) -> None:
    """Processa resposta em áudio: transcreve, gera feedback visual, continua conversa."""

    await whatsapp_service.send_text(phone, MESSAGES["processing"])

    # 1. Baixa o áudio
    audio_path = await _download_audio(message_id, raw_data)
    if not audio_path:
        await whatsapp_service.send_text(
            phone, "😅 Não consegui processar seu áudio. Tente novamente!"
        )
        return

    # 2. Transcreve
    transcription = await openai_service.transcribe_audio(audio_path)
    if not transcription:
        await whatsapp_service.send_text(
            phone, "😅 Não consegui entender o áudio. Tente novamente!"
        )
        return

    # 3. Corrige
    correction = await openai_service.correct_text(transcription)

    # 4. Gera imagem de feedback (sem tips — ficam no texto)
    image_id = generate_id()
    image_path = image_service.generate_feedback_image(correction, image_id)

    # 5. Envia imagem sozinha
    await whatsapp_service.send_image(phone, image_path)

    # 6. Envia tips como texto separado
    tips = correction.get("tips", [])
    if tips:
        tips_text = "\n".join(f"💡 {tip}" for tip in tips)
        await whatsapp_service.send_text(phone, f"📚 *Dicas:*\n\n{tips_text}")

    # 7. Continua a conversa (responde ao que o aluno disse)
    reply = await openai_service.chat_response(session, transcription)

    # 8. Envia resposta em áudio (porque o aluno mandou áudio)
    audio_id = generate_id()
    reply_audio = await openai_service.text_to_speech(reply, audio_id)
    await whatsapp_service.send_audio(phone, reply_audio)

    # Também envia texto para referência
    await whatsapp_service.send_text(phone, f"📝 _{reply}_")


async def _handle_text_response(phone: str, text: str, session) -> None:
    """Processa resposta em texto: corrige e continua conversa (sem áudio)."""

    # 1. Corrige o texto
    correction = await openai_service.correct_text(text)

    # 2. Monta mensagem de correção
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
        # Sem erros — só elogia
        encouragement = correction.get("encouragement", "Perfect! No errors!")
        await whatsapp_service.send_text(phone, f"✅ {encouragement}")

    # 3. Continua a conversa (apenas texto, sem áudio)
    reply = await openai_service.chat_response(session, text)
    await whatsapp_service.send_text(phone, f"🎓 _{reply}_")


# ─────────────────────────────────────────────
# Funções auxiliares
# ─────────────────────────────────────────────

def _extract_text(data: dict) -> str | None:
    """Extrai o texto de diferentes tipos de mensagem."""
    message = data.get("message", {})

    # Texto simples
    if "conversation" in message:
        return message["conversation"]

    # Mensagem estendida
    if "extendedTextMessage" in message:
        return message["extendedTextMessage"].get("text")

    return None


async def _download_audio(message_id: str, raw_data: dict) -> Path | None:
    """
    Baixa áudio da mensagem.
    Tenta via base64 da Evolution API primeiro, depois via URL direta.
    """
    try:
        audio_path = AUDIO_CACHE_DIR / f"{generate_id()}.ogg"

        # Tenta obter via base64
        try:
            media_data = await whatsapp_service.get_media_base64(message_id)
            if media_data and "base64" in media_data:
                audio_bytes = base64.b64decode(media_data["base64"])
                audio_path.write_bytes(audio_bytes)
                logger.info("Áudio baixado via base64: %s", audio_path)
                return audio_path
        except Exception as e:
            logger.warning("Falha ao obter áudio via base64: %s", e)

        # Fallback: tenta URL direta da mensagem
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