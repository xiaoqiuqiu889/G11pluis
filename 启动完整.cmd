@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title G1N Full Stack Launcher
cd /d "%~dp0"

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "G1N_PORT=%BACKEND_PORT%"
set "G1N_HOST=127.0.0.1"
set "G1N_LOG_LEVEL=INFO"

REM ---- 1. Check Python ----
where python.exe >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python 3.12+ was not found in PATH.
  pause
  exit /b 1
)

REM ---- 2. Check Node.js ----
set "NODE_OK="
where node.exe >nul 2>nul
if not errorlevel 1 (
  node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)" >nul 2>nul
  if not errorlevel 1 set "NODE_OK=1"
)
if not defined NODE_OK (
  echo.
  echo [ERROR] Node.js 22.13 or newer was not found.
  echo Install the current Node.js LTS release, then double-click this file again:
  echo   https://nodejs.org/
  pause
  exit /b 1
)

REM ---- 3. Check package manager ----
set "PM="
set "PM_CMD="
for /f "delims=" %%P in ('where pnpm.cmd 2^>nul') do if not defined PM_CMD set "PM_CMD=%%P" && set "PM=pnpm"
if not defined PM_CMD (
  for /f "delims=" %%P in ('where npm.cmd 2^>nul') do if not defined PM_CMD set "PM_CMD=%%P" && set "PM=npm"
)
if not defined PM_CMD (
  echo.
  echo [ERROR] No Node.js package manager (npm / pnpm) was found.
  pause
  exit /b 1
)

REM ---- 4. Check client dir ----
if not exist "client\package.json" (
  echo.
  echo [ERROR] client\package.json not found.
  pause
  exit /b 1
)

REM ---- 5. Install client deps if needed ----
if not exist "client\node_modules" (
  echo.
  echo First launch: installing client dependencies (~2-3 minutes)...
  echo Package manager: !PM!
  echo.
  pushd "client"
  if /i "!PM!"=="pnpm" (
    call "!PM_CMD!" install --prefer-offline
  ) else (
    call "!PM_CMD!" install
  )
  if errorlevel 1 (
    popd
    echo.
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
  )
  popd
)

REM ---- 6. Kill existing backend process on BACKEND_PORT ----
netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo [INFO] Killing existing process on port %BACKEND_PORT%...
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%BACKEND_PORT% .*LISTENING"') do (
    taskkill /F /PID %%P >nul 2>nul
  )
  timeout /t 2 /nobreak >nul
)

REM ---- 7. Print banner ----
echo.
echo ==============================================
echo   G1N - Revolution Street AI Native
echo   FULL STACK (frontend + backend + DB)
echo   Backend:  http://%G1N_HOST%:%BACKEND_PORT%/
echo   Frontend: http://localhost:%FRONTEND_PORT%/
echo   Mode:     VITE_USE_MOCK=false (real server)
echo ==============================================
echo.

REM ---- 8. Start FastAPI backend in a separate window ----
echo Starting FastAPI backend in a separate window...
if not exist "data" mkdir data
start "G1N-Backend" /D "%~dp0" cmd /c "python -m uvicorn server.app:app --host %G1N_HOST% --port %BACKEND_PORT% --log-level info > data\server.log 2>&1"

REM ---- 9. Wait for backend up ----
set "BACKEND_READY="
for /l %%I in (1,1,20) do (
  if not defined BACKEND_READY (
    netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul 2>nul
    if not errorlevel 1 (
      set "BACKEND_READY=1"
    ) else (
      timeout /t 1 /nobreak >nul
    )
  )
)
if not defined BACKEND_READY (
  echo.
  echo [WARN] Backend didn't start within 20 seconds.
  echo Check the "G1N-Backend" window for errors.
  echo.
) else (
  echo Backend ready.
)

REM ---- 10. Start Vite dev server (VITE_USE_MOCK=false) ----
echo.
echo Starting Vite dev server (VITE_USE_MOCK=false)...
echo.
REM 通过临时 helper 脚本传环境变量，绕开 cmd /c 引号嵌套问题
set "VITE_LAUNCHER=%TEMP%\g1n_vite_launcher_%RANDOM%.cmd"
> "%VITE_LAUNCHER%" echo @echo off
>> "%VITE_LAUNCHER%" echo set VITE_USE_MOCK=false
>> "%VITE_LAUNCHER%" echo cd /d "%~dp0client"
>> "%VITE_LAUNCHER%" echo call "!PM_CMD!" run dev
start "G1N-Frontend" cmd /c "\"%VITE_LAUNCHER%\""
set "VITE_LAUNCHER="

REM ---- 11. Wait for frontend up ----
set "FRONTEND_READY="
for /l %%I in (1,1,30) do (
  if not defined FRONTEND_READY (
    netstat -ano | findstr /R /C:":%FRONTEND_PORT% .*LISTENING" >nul 2>nul
    if not errorlevel 1 (
      set "FRONTEND_READY=1"
    ) else (
      timeout /t 1 /nobreak >nul
    )
  )
)
if not defined FRONTEND_READY (
  echo.
  echo [WARN] Frontend didn't start within 20 seconds.
  echo Check the "G1N-Frontend" window for errors.
  echo.
)

REM ---- 12. Open browser ----
echo.
echo ==============================================
echo   Game URL:    http://localhost:%FRONTEND_PORT%/
echo   API health:  http://%G1N_HOST%:%BACKEND_PORT%/health
echo   API docs:    http://%G1N_HOST%:%BACKEND_PORT%/docs
echo ==============================================
echo.
echo Two background windows are running. Don't close them:
echo   - "G1N-Backend"  (FastAPI on port %BACKEND_PORT%)
echo   - "G1N-Frontend" (Vite on port %FRONTEND_PORT%)
echo.
echo To stop:  Close both background windows.
echo.
start "" "http://localhost:%FRONTEND_PORT%/"
echo Game opened in your browser.
echo.
timeout /t 3 /nobreak >nul
exit /b 0
