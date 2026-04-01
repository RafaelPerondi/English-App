"""
Ponto de entrada do English Teacher Bot.
Rode com: python main.py
"""

import uvicorn

from config import settings
from app.utils.helpers import setup_logging
from app.server import create_app

# Configura logging antes de tudo
setup_logging()

# Cria a aplicação
app = create_app()

if __name__ == "__main__":
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     🎓 English Teacher Bot v1.0.0        ║")
    print("  ╠══════════════════════════════════════════╣")
    print(f"  ║  Servidor: http://localhost:{settings.server_port}        ║")
    print(f"  ║  Docs:     http://localhost:{settings.server_port}/docs   ║")
    print(f"  ║  Webhook:  /webhook/messages             ║")
    print("  ║                                          ║")
    print("  ║  ⚠️  Lembre de rodar o ngrok:             ║")
    print(f"  ║  ngrok http {settings.server_port}                       ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    uvicorn.run(
        "main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
        reload_excludes=["*.log", "audio_cache/*", "*.pyc"],
        log_level="info",
    )
