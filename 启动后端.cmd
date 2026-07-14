@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title G1N Backend Server
cd /d "%~dp0"

set "PORT=8000"
set "G1N_PORT=8000"
set "G1N_HOST=127.0.0.1"
set "G1N_LOG_LEVEL=INFO"

REM ---- 1. Check Python ----
where python.exe >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python 3.12+ was not found in PATH.
  echo Install Python 3.12 or newer from https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python 3.12 or newer is required.
  python --version
  pause
  exit /b 1
)

REM ---- 2. Check server dir ----
if not exist "server\app.py" (
  echo.
  echo [ERROR] server\app.py not found.
  pause
  exit /b 1
)

REM ---- 3. Check Python deps ----
python -c "import fastapi, uvicorn, sqlalchemy, alembic, jsonschema" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [WARN] Some Python deps are missing. Installing...
  pip install fastapi "uvicorn[standard]" sqlalchemy alembic jsonschema pydantic pyyaml asyncpg
  if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed.
    pause
    exit /b 1
  )
)

REM ---- 4. Kill existing process on PORT ----
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo [INFO] Killing existing process on port %PORT%...
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    taskkill /F /PID %%P >nul 2>nul
  )
  timeout /t 2 /nobreak >nul
)

REM ---- 5. Start FastAPI backend ----
echo.
echo ==============================================
echo   G1N Backend Server
echo   http://%G1N_HOST%:%PORT%/
echo   Mode:    default
echo   DB:      ./data/g1n.db (auto-created)
echo   LLM:     mock (no API key required)
echo ==============================================
echo.
echo Press Ctrl+C to stop the server.
echo.

cd /d "%~dp0"
if not exist "data" mkdir data
start "G1N-Backend" /B cmd /c "python -m uvicorn server.app:app --host %G1N_HOST% --port %PORT% --log-level info > data\server.log 2>&1"

REM ---- 6. Wait for server up ----
set "SERVER_READY="
for /l %%I in (1,1,20) do (
  if not defined SERVER_READY (
    netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>nul
    if not errorlevel 1 (
      set "SERVER_READY=1"
    ) else (
      timeout /t 1 /nobreak >nul
    )
  )
)

if not defined SERVER_READY (
  echo.
  echo [WARN] Server didn't start within 20 seconds.
  echo Check the "G1N-Backend" window for errors.
  echo.
) else (
  echo.
  echo ==============================================
  echo   Server ready at http://%G1N_HOST%:%PORT%/
  echo   Try:    http://%G1N_HOST%:%PORT%/health
  echo   Docs:   http://%G1N_HOST%:%PORT%/docs
  echo ==============================================
  echo.
  echo To stop:  Close the "G1N-Backend" window
  echo.
  timeout /t 3 /nobreak >nul
)

exit /b 0
