"""
Serviço de integração com o WhatsApp via Evolution API v2.
Responsável por enviar mensagens de texto, áudio, imagens e enquetes.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def _base_url() -> str:
    return f"{settings.evolution_api_url}"


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "apikey": settings.evolution_api_key,
    }


def _format_phone(phone: str) -> str:
    return phone.replace("+", "").replace("-", "").replace(" ", "")


def _detect_audio_mime(path: Path) -> str:
    mime_map = {
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".m4a": "audio/mp4", ".opus": "audio/opus",
    }
    return mime_map.get(path.suffix.lower(), "audio/mpeg")


def _detect_image_mime(path: Path) -> str:
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    return mime_map.get(path.suffix.lower(), "image/png")


# ─────────────────────────────────────────────
# Envio de mensagens
# ─────────────────────────────────────────────

async def send_text(phone: str, text: str) -> bool:
    url = f"{_base_url()}/message/sendText/{settings.evolution_instance}"
    payload = {"number": _format_phone(phone), "text": text}
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
    url = f"{_base_url()}/message/sendWhatsAppAudio/{settings.evolution_instance}"
    try:
        audio_bytes = audio_path.read_bytes()
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {"number": _format_phone(phone), "audio": audio_base64}
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        logger.info("Áudio enviado com sucesso para %s", phone)
        return True
    except Exception as e:
        logger.error("Erro ao enviar áudio para %s: %s", phone, e)
        return False


async def send_image(phone: str, image_path: Path, caption: str = "") -> bool:
    url = f"{_base_url()}/message/sendMedia/{settings.evolution_instance}"
    image_bytes = image_path.read_bytes()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    mimetype = _detect_image_mime(image_path)
    suffix = image_path.suffix.lower().lstrip(".")
    payload = {
        "number": _format_phone(phone), "mediatype": "image",
        "mimetype": mimetype, "caption": caption,
        "media": image_base64, "fileName": f"feedback.{suffix}",
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


async def send_poll(phone: str, title: str, options: list[str]) -> bool:
    """
    Envia enquete interativa no WhatsApp.
    O aluno toca na opção em vez de digitar.
    Funciona com Baileys (botões tradicionais não funcionam).
    """
    url = f"{_base_url()}/message/sendPoll/{settings.evolution_instance}"
    payload = {
        "number": _format_phone(phone),
        "name": title,
        "selectableCount": 1,
        "values": options,
    }
    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        logger.info("Enquete enviada para %s", phone)
        return True
    except httpx.HTTPError as e:
        logger.error("Erro ao enviar enquete para %s: %s", phone, e)
        return False


# ─────────────────────────────────────────────
# Download de mídia
# ─────────────────────────────────────────────

async def download_media(media_url: str, save_path: Path) -> Path:
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
    url = f"{_base_url()}/chat/getBase64FromMediaMessage/{settings.evolution_instance}"
    payload = {"message": {"key": {"id": message_id}}, "convertToMp4": False}
    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error("Erro ao obter mídia base64: %s", e)
        raise


async def close() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
