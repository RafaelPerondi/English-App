@echo off
title English Teacher Bot - Setup
echo.
echo  ============================================
echo   English Teacher Bot - Instalacao
echo  ============================================
echo.

:: Verifica Python
python --version 2>nul
if errorlevel 1 (
    echo  [ERRO] Python nao encontrado!
    echo  Instale o Python 3.10, 3.11, 3.12 ou 3.13
    echo  https://python.org/downloads
    echo.
    echo  IMPORTANTE: NAO use Python 3.14 (beta)
    pause
    exit /b 1
)
echo  [OK] Python encontrado

:: Cria ambiente virtual
if not exist "venv" (
    echo  [..] Criando ambiente virtual...
    python -m venv venv
    echo  [OK] Ambiente virtual criado
) else (
    echo  [OK] Ambiente virtual ja existe
)

:: Ativa venv e instala dependencias
echo  [..] Instalando dependencias...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt
echo  [OK] Dependencias instaladas

:: Cria .env se nao existe
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo  ============================================
    echo   IMPORTANTE: Configure o arquivo .env
    echo  ============================================
    echo.
    echo  Abra o arquivo .env e preencha:
    echo    - OPENAI_API_KEY
    echo    - EVOLUTION_API_URL
    echo    - EVOLUTION_API_KEY
    echo    - EVOLUTION_INSTANCE
    echo    - NGROK_URL
    echo.
) else (
    echo  [OK] Arquivo .env ja existe
)

:: Cria pastas necessarias
if not exist "audio_cache" mkdir audio_cache
if not exist "assets\fonts" mkdir assets\fonts

echo.
echo  ============================================
echo   Setup concluido!
echo  ============================================
echo.
echo  Proximos passos:
echo    1. Edite o .env com suas credenciais
echo    2. Abra outro terminal e rode: ngrok http 8000
echo    3. Copie a URL do ngrok para o .env
echo    4. Rode: start.bat
echo.
pause
