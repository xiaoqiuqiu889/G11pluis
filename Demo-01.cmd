@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title G1N Demo 01 Launcher
cd /d "%~dp0"

set "ROOT=%~dp0"
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "DEMO_URL=http://localhost:%FRONTEND_PORT%/scene/photo_lab_2008"

echo.
echo ============================================================
echo   G1N Demo 01 - case 01 / photo_lab_2008
echo   Client: real API mode  ^(VITE_USE_MOCK=false^)
echo   Server: deterministic mock LLM ^(G1N_USE_MOCK=1^)
echo ============================================================
echo.

REM Never kill an unrelated process. A stale frontend may have been
REM compiled in mock mode, so an occupied 5173 is treated as unsafe.
for %%F in ("server\app.py" "client\package.json") do (
  if not exist %%F (
    echo [ERROR] Missing %%~F. Run this file from the repository root.
    pause
    exit /b 1
  )
)

where python.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.12 or newer was not found in PATH.
  pause
  exit /b 1
)
python -c "import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.12 or newer is required.
  python --version
  pause
  exit /b 1
)

where node.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 22.13 or newer was not found in PATH.
  pause
  exit /b 1
)
node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 22.13 or newer is required.
  node --version
  pause
  exit /b 1
)

set "PM_CMD="
set "PM_NAME="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do (
  if not defined PM_CMD (
    set "PM_CMD=%%P"
    set "PM_NAME=npm"
  )
)
if not defined PM_CMD for /f "delims=" %%P in ('where pnpm.cmd 2^>nul') do (
  if not defined PM_CMD (
    set "PM_CMD=%%P"
    set "PM_NAME=pnpm"
  )
)
if not defined PM_CMD (
  echo [ERROR] npm or pnpm was not found in PATH.
  pause
  exit /b 1
)

REM First-run dependency bootstrap, matching the repository's backend launcher.
python -c "import fastapi,uvicorn,sqlalchemy,alembic,jsonschema,pydantic,yaml" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing missing Python dependencies...
  python -m pip install fastapi "uvicorn[standard]" sqlalchemy alembic jsonschema pydantic pyyaml asyncpg
  if errorlevel 1 (
    echo [ERROR] Python dependency installation failed.
    pause
    exit /b 1
  )
)

if not exist "client\node_modules" (
  echo [INFO] Installing client dependencies with !PM_NAME!...
  pushd "client"
  if /i "!PM_NAME!"=="pnpm" (
    call "!PM_CMD!" install --prefer-offline
  ) else (
    call "!PM_CMD!" install
  )
  if errorlevel 1 (
    popd
    echo [ERROR] Client dependency installation failed.
    pause
    exit /b 1
  )
  popd
)

if /i "%~1"=="--check" (
  echo [OK] Demo prerequisites are installed.
  echo [OK] Direct scene URL: %DEMO_URL%
  exit /b 0
)

REM Reuse port 8000 only when it identifies itself as this G1N server.
set "BACKEND_READY="
powershell -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://%BACKEND_HOST%:%BACKEND_PORT%/health' -TimeoutSec 2;if($r.status -eq 'ok' -and $r.service -eq 'g1n-server' -and $r.llm.isMock -eq $true){exit 0}}catch{};exit 1" >nul 2>nul
if not errorlevel 1 set "BACKEND_READY=1"
if not defined BACKEND_READY (
  netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul 2>nul
  if not errorlevel 1 (
    echo [ERROR] Port %BACKEND_PORT% is occupied by a non-G1N or unhealthy service.
    echo         Stop it manually; this launcher will not kill other processes.
    pause
    exit /b 1
  )
  if not exist "data" mkdir "data"
  echo [INFO] Starting FastAPI on %BACKEND_HOST%:%BACKEND_PORT%...
  start "G1N-Demo01-Backend" /D "%ROOT%" cmd /k "set G1N_USE_MOCK=1&&set G1N_HOST=%BACKEND_HOST%&&set G1N_PORT=%BACKEND_PORT%&&python -m uvicorn server.app:app --host %BACKEND_HOST% --port %BACKEND_PORT% --log-level info"
  for /l %%I in (1,1,30) do (
    if not defined BACKEND_READY (
      powershell -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://%BACKEND_HOST%:%BACKEND_PORT%/health' -TimeoutSec 1;if($r.status -eq 'ok' -and $r.service -eq 'g1n-server' -and $r.llm.isMock -eq $true){exit 0}}catch{};exit 1" >nul 2>nul
      if not errorlevel 1 (
        set "BACKEND_READY=1"
      ) else (
        timeout /t 1 /nobreak >nul
      )
    )
  )
) else (
  echo [INFO] Reusing healthy G1N backend on port %BACKEND_PORT%.
)
if not defined BACKEND_READY (
  echo [ERROR] Backend did not become healthy within 30 seconds.
  echo         Inspect the G1N-Demo01-Backend window.
  pause
  exit /b 1
)

REM Gate the demo on the exact content contract we are about to present.
powershell -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://%BACKEND_HOST%:%BACKEND_PORT%/v1/scenes/photo_lab_2008' -TimeoutSec 3;if($r.sceneId -eq 'photo_lab_2008'){exit 0}}catch{};exit 1" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend is healthy but photo_lab_2008 metadata is unavailable.
  pause
  exit /b 1
)

set "PREFERRED_FRONTEND_PORT=%FRONTEND_PORT%"
set "FRONTEND_PORT="
for /l %%P in (5173,1,5199) do (
  if not defined FRONTEND_PORT (
    netstat -ano | findstr /R /C:":%%P .*LISTENING" >nul 2>nul
    if errorlevel 1 set "FRONTEND_PORT=%%P"
  )
)
if not defined FRONTEND_PORT (
  echo [ERROR] No free frontend port was found in range 5173-5199.
  pause
  exit /b 1
)
set "DEMO_URL=http://localhost:!FRONTEND_PORT!/scene/photo_lab_2008"
if not "!FRONTEND_PORT!"=="!PREFERRED_FRONTEND_PORT!" (
  echo [INFO] Port !PREFERRED_FRONTEND_PORT! is occupied; using !FRONTEND_PORT! instead.
)

echo [INFO] Starting Vite in real-backend mode...
set "VITE_LAUNCHER=%TEMP%\g1n_demo01_vite_%RANDOM%.cmd"
>"%VITE_LAUNCHER%" echo @echo off
>>"%VITE_LAUNCHER%" echo set VITE_USE_MOCK=false
>>"%VITE_LAUNCHER%" echo set VITE_API_BASE=http://%BACKEND_HOST%:%BACKEND_PORT%
>>"%VITE_LAUNCHER%" echo cd /d "%ROOT%client"
>>"%VITE_LAUNCHER%" echo call "!PM_CMD!" run dev -- --host localhost --port %FRONTEND_PORT% --strictPort
start "G1N-Demo01-Frontend" cmd /k ""%VITE_LAUNCHER%""

set "FRONTEND_READY="
for /l %%I in (1,1,30) do (
  if not defined FRONTEND_READY (
    powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:%FRONTEND_PORT%/scene/photo_lab_2008' -TimeoutSec 1;if($r.StatusCode -eq 200 -and $r.Content -match 'id=\"root\"'){exit 0}}catch{};exit 1" >nul 2>nul
    if not errorlevel 1 (
      set "FRONTEND_READY=1"
    ) else (
      timeout /t 1 /nobreak >nul
    )
  )
)
if not defined FRONTEND_READY (
  echo [ERROR] Frontend did not become ready within 30 seconds.
  echo         Inspect the G1N-Demo01-Frontend window.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   DEMO READY
echo   %DEMO_URL%
echo   API health: http://%BACKEND_HOST%:%BACKEND_PORT%/health
echo ============================================================
echo.
if /i not "%DEMO_NO_BROWSER%"=="1" start "" "%DEMO_URL%"
echo Close the two Demo 01 windows to stop the stack.
timeout /t 3 /nobreak >nul
exit /b 0
