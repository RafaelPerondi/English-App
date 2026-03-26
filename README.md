# 🎓 English Teacher Bot — WhatsApp

Bot professor de inglês via WhatsApp usando IA (OpenAI GPT + Whisper + TTS).

## Arquitetura

```
english_teacher_bot/
├── main.py                  # Ponto de entrada
├── config.py                # Configurações centralizadas
├── .env.example             # Variáveis de ambiente (template)
├── requirements.txt
├── app/
│   ├── server.py            # App FastAPI
│   ├── routes/
│   │   └── webhook.py       # Endpoints do webhook
│   ├── services/
│   │   ├── openai_service.py    # GPT, Whisper, TTS
│   │   ├── whatsapp_service.py  # Evolution API
│   │   ├── session_manager.py   # Gerenciamento de sessões
│   │   └── image_service.py     # Geração de imagens (Pillow)
│   ├── models/
│   │   └── session.py       # Modelos de dados
│   └── utils/
│       └── helpers.py       # Funções auxiliares
├── assets/
│   └── fonts/               # Fontes para imagens
└── audio_cache/             # Cache temporário de áudios
```

## Pré-requisitos

1. **Python 3.10+**
2. **Conta OpenAI** com créditos (API Key)
3. **Evolution API** rodando (local ou servidor)
4. **ngrok** instalado (para expor o servidor local)
5. **Chip pré-pago** conectado à Evolution API

## Instalação

```bash
# 1. Clone ou copie o projeto
cd english_teacher_bot

# 2. Crie um ambiente virtual
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure o .env
copy .env.example .env
# Edite o .env com suas credenciais

# 5. Inicie o ngrok (em outro terminal)
.\ngrok http 8000

# 6. Copie a URL do ngrok para o .env (NGROK_URL)

# 7. Rode o bot
python main.py
```

## Configuração da Evolution API

1. Crie uma instância na Evolution API
2. Conecte o chip (QR Code)
3. Configure o webhook apontando para: `{NGROK_URL}/webhook/messages`
4. Eventos: `MESSAGES_UPSERT`

## Fluxo do Bot

```
Cliente envia msg → Bot pede nome
                  → Bot pede nível (A/B/C)
                  → Bot pede tema
                  → Bot envia áudio sobre o tema
                  → Cliente responde (áudio ou texto)
                      ├── Áudio: Imagem com transcrição + correção + dicas
                      └── Texto: Correção por texto
```

## Próximos Passos (preparado para)

- [ ] Banco de dados (PostgreSQL/SQLite)
- [ ] Sistema de pagamentos (Stripe/Mercado Pago)
- [ ] Painel administrativo
- [ ] Múltiplos idiomas
- [ ] Histórico de progresso do aluno
- [ ] Níveis mais granulares
