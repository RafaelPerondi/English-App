"""
Serviço de integração com o WhatsApp via Evolution API v2.
Responsável por enviar mensagens de texto, áudio e imagens.

MIGRADO de v1 para v2:
- Payloads de envio agora são flat (sem wrappers aninhados)
- Campo "mimetype" obrigatório no sendMedia
- Endpoint getBase64 renomeado
- Campo "audio" aceita data URI base64
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Cliente HTTP reutilizável
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Retorna o cliente HTTP singleton."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def _base_url() -> str:
    """URL base da Evolution API para a instância configurada."""
    return f"{settings.evolution_api_url}"


def _headers() -> dict:
    """Headers padrão para requisições à Evolution API."""
    return {
        "Content-Type": "application/json",
        "apikey": settings.evolution_api_key,
    }


def _format_phone(phone: str) -> str:
    """Garante que o telefone está no formato correto (apenas números)."""
    return phone.replace("+", "").replace("-", "").replace(" ", "")


def _detect_audio_mime(path: Path) -> str:
    """Detecta o mimetype de áudio pelo sufixo do arquivo."""
    mime_map = {
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".opus": "audio/opus",
    }
    return mime_map.get(path.suffix.lower(), "audio/mpeg")


def _detect_image_mime(path: Path) -> str:
    """Detecta o mimetype de imagem pelo sufixo do arquivo."""
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(path.suffix.lower(), "image/png")


# ─────────────────────────────────────────────
# Envio de mensagens (v2 — payloads flat)
# ─────────────────────────────────────────────

async def send_text(phone: str, text: str) -> bool:
    """Envia mensagem de texto simples."""
    url = f"{_base_url()}/message/sendText/{settings.evolution_instance}"

    # v2: payload flat — campo "text" direto na raiz
    payload = {
        "number": _format_phone(phone),
        "text": text,
    }

    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        logger.info("Texto enviado para %s", phone)
        return True
    except httpx.HTTPError as e:
        logger.error("Erro ao enviar texto para %s: %s", phone, e)
        return False


async def send_audio(phone: str, audio_path: Path) -> bool:
    """Envia mensagem de áudio como mensagem de voz (PTT)."""
    url = f"{_base_url()}/message/sendWhatsAppAudio/{settings.evolution_instance}"

    try:
        # Lê o arquivo e converte para base64
        audio_bytes = audio_path.read_bytes()
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        mimetype = _detect_audio_mime(audio_path)

        # v2: payload flat — "audio" aceita URL ou data URI base64
        payload = {
            "number": _format_phone(phone),
            "audio": audio_base64,
        }

        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()

        logger.info("Áudio enviado com sucesso para %s", phone)
        return True
    except Exception as e:
        logger.error("Erro ao enviar áudio para %s: %s", phone, e)
        return False


async def send_image(phone: str, image_path: Path, caption: str = "") -> bool:
    """Envia imagem com legenda opcional."""
    url = f"{_base_url()}/message/sendMedia/{settings.evolution_instance}"

    image_bytes = image_path.read_bytes()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    mimetype = _detect_image_mime(image_path)
    suffix = image_path.suffix.lower().lstrip(".")

    # v2: payload flat — sem wrapper "mediaMessage", "mimetype" obrigatório
    payload = {
        "number": _format_phone(phone),
        "mediatype": "image",
        "mimetype": mimetype,
        "caption": caption,
        "media": image_base64,
        "fileName": f"feedback.{suffix}",
    }

    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        logger.info("Imagem enviada para %s", phone)
        return True
    except httpx.HTTPError as e:
        logger.error("Erro ao enviar imagem para %s: %s", phone, e)
        return False


# ─────────────────────────────────────────────
# Download de mídia
# ─────────────────────────────────────────────

async def download_media(media_url: str, save_path: Path) -> Path:
    """
    Baixa mídia (áudio/imagem) de uma URL da Evolution API.
    Retorna o caminho do arquivo salvo.
    """
    try:
        client = _get_client()
        response = await client.get(media_url, headers=_headers())
        response.raise_for_status()
        save_path.write_bytes(response.content)
        logger.info("Mídia baixada: %s", save_path)
        return save_path
    except httpx.HTTPError as e:
        logger.error("Erro ao baixar mídia: %s", e)
        raise


async def get_media_base64(message_id: str) -> dict:
    """
    Obtém mídia em base64 pelo ID da mensagem.
    Útil para áudios que não têm URL direta.
    """
    # v2: endpoint renomeado de "getBase64FromMediaMessage" → "getBase64"
    url = f"{_base_url()}/chat/getBase64FromMediaMessage/{settings.evolution_instance}"
    payload = {
        "message": {"key": {"id": message_id}},
        "convertToMp4": False,
    }

    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error("Erro ao obter mídia base64: %s", e)
        raise


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

async def close() -> None:
    """Fecha o cliente HTTP."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
