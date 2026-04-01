"""
Configurações centralizadas do bot.
Carrega variáveis do .env e valida automaticamente.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
AUDIO_CACHE_DIR = BASE_DIR / "audio_cache"

# Garante que os diretórios existam
AUDIO_CACHE_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Configurações carregadas automaticamente do arquivo .env"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str

    # Evolution API
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = "english-teacher"

    # ngrok
    ngrok_url: str = ""

    # Servidor
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # Bot
    bot_language: str = "pt-BR"
    session_timeout_minutes: int = 60


settings = Settings()
