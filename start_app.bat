@echo off
REM ======================================================
REM   DOCSEARCH PT - Arranque automático (Elasticsearch + App)
REM ======================================================

REM --- Caminhos principais ---
set BASE_DIR=%~dp0
set VENV_DIR=%BASE_DIR%.venv
set ES_DIR=C:\Elasticsearch
set APP_DIR=%BASE_DIR%webapp
set APP_SCRIPT=%APP_DIR%\app.py

REM --- Porta do Elasticsearch ---
set ES_PORT=9200
set ES_URL=http://127.0.0.1:%ES_PORT%
set "PATH=%VENV_DIR%\Scripts;%PATH%"

echo.
echo =============================================
echo 🟢 A iniciar DocSearch PT...
echo 📁 Diretório base: %BASE_DIR%
echo =============================================

REM --- 1. Verifica se Elasticsearch já está a correr ---
echo 🔍 A verificar Elasticsearch...
for /f "tokens=2 delims=:" %%a in ('netstat -ano ^| findstr :%ES_PORT%') do (
    set ES_FOUND=1
)
if not defined ES_FOUND (
    echo 🚀 A iniciar Elasticsearch...
    start "Elasticsearch" cmd /c "%ES_DIR%\bin\elasticsearch.bat"
    echo ⏳ A aguardar 30 segundos pelo arranque do Elasticsearch...
    timeout /t 30 /nobreak >nul
) else (
    echo ✅ Elasticsearch já está ativo.
)

REM --- 2. Inicia a aplicação FastAPI ---
echo 🚀 A iniciar a aplicação (app.py)...
cd /d "%APP_DIR%"
start "DocSearch App" cmd /k "..\.venv\Scripts\python.exe" "app.py"

echo.
echo 🌍 A aplicação está a iniciar...
echo 🔗 Acede em: http://127.0.0.1:8000
echo =============================================
pause
