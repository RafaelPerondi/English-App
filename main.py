"""
English Teacher Bot — entrypoint.

Production: started via `docker compose up -d` (see Dockerfile CMD).
Development: run locally with `python main.py`, auto-reload disabled by default.
Set DEV_RELOAD=true in .env to enable reload locally.
"""
import os
import logging

import uvicorn

from config import settings
from app.utils.helpers import setup_logging
from app.server import create_app

setup_logging()
logger = logging.getLogger(__name__)

# Export for uvicorn workers (`main:app`)
app = create_app()


def _banner() -> None:
    logger.info("─" * 60)
    logger.info("English Teacher Bot v1.0.0")
    logger.info("Listening on %s:%d", settings.server_host, settings.server_port)
    logger.info("Docs:    http://%s:%d/docs", settings.server_host, settings.server_port)
    logger.info("Webhook: /webhook/messages")
    logger.info("─" * 60)


if __name__ == "__main__":
    dev_reload = os.getenv("DEV_RELOAD", "").lower() in {"1", "true", "yes"}
    _banner()
    uvicorn.run(
        "main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=dev_reload,
        log_level="info",
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
