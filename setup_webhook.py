"""
Script para configurar o webhook da Evolution API.
Rode após ter o ngrok e a Evolution API funcionando.

Uso: python setup_webhook.py
"""

import httpx
from config import settings


def setup_webhook() -> None:
    """Configura o webhook na Evolution API para receber mensagens."""

    if not settings.ngrok_url:
        print("❌ NGROK_URL não configurada no .env!")
        print("   1. Rode: ngrok http 8000")
        print("   2. Copie a URL https://xxxx.ngrok-free.app")
        print("   3. Cole no .env em NGROK_URL")
        return

    webhook_url = f"{settings.ngrok_url}/webhook/messages"
    api_url = (
        f"{settings.evolution_api_url}/webhook/set/"
        f"{settings.evolution_instance}"
    )

    payload = {
        "url": webhook_url,
        "webhook_by_events": False,
        "webhook_base64": True,
        "events": [
            "MESSAGES_UPSERT",
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": settings.evolution_api_key,
    }

    print(f"📡 Configurando webhook...")
    print(f"   URL: {webhook_url}")
    print(f"   Instância: {settings.evolution_instance}")
    print()

    try:
        response = httpx.post(api_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print("✅ Webhook configurado com sucesso!")
        print(f"   Resposta: {response.json()}")
    except httpx.HTTPStatusError as e:
        print(f"❌ Erro HTTP: {e.response.status_code}")
        print(f"   Resposta: {e.response.text}")
    except httpx.ConnectError:
        print(f"❌ Não foi possível conectar à Evolution API em:")
        print(f"   {settings.evolution_api_url}")
        print("   Verifique se a Evolution API está rodando.")
    except Exception as e:
        print(f"❌ Erro: {e}")


if __name__ == "__main__":
    setup_webhook()
