@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title G1N Client (mock mode)
cd /d "%~dp0"

echo.
echo ==============================================
echo   G1N - Revolution Street AI Native
echo   CLIENT launcher (mock mode, no backend)
echo ==============================================
echo.
echo For the FULL stack (frontend + backend + DB), use
echo     启动完整.cmd
echo.
echo For the BACKEND only, use
echo     启动后端.cmd
echo.
echo ==============================================
echo.

set "PORT=5173"
set "GAME_URL=http://localhost:%PORT%/"
set "CLIENT_DIR=%~dp0client"

REM ---- 1. Check Node.js ----
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

REM ---- 2. Check package manager ----
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

REM ---- 3. Check client dir ----
if not exist "%CLIENT_DIR%\package.json" (
  echo.
  echo [ERROR] client\package.json not found.
  pause
  exit /b 1
)

REM ---- 4. Install deps if needed ----
if not exist "%CLIENT_DIR%\node_modules" (
  echo.
  echo First launch: installing client dependencies (~2-3 minutes)...
  echo Package manager: !PM!
  echo.
  pushd "%CLIENT_DIR%"
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

REM ---- 5. Check if port is in use ----
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo Server is already running on port %PORT%. Opening browser...
  start "" "%GAME_URL%"
  exit /b 0
)

REM ---- 6. Start Vite dev server in background ----
echo.
echo Starting G1N (mock mode)...
echo.
echo Server output will appear in a new window. Don't close it.
echo.
REM 通过临时 helper 脚本绕开 cmd /k 引号嵌套问题
set "VITE_LAUNCHER=%TEMP%\g1n_vite_launcher_%RANDOM%.cmd"
> "%VITE_LAUNCHER%" echo @echo off
>> "%VITE_LAUNCHER%" echo set VITE_USE_MOCK=true
>> "%VITE_LAUNCHER%" echo cd /d "%CLIENT_DIR%"
>> "%VITE_LAUNCHER%" echo call "!PM_CMD!" run dev
start "G1N-Client" cmd /k "\"%VITE_LAUNCHER%\""
set "VITE_LAUNCHER="

REM ---- 7. Wait for server up ----
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
  echo Check the "G1N-Client" window for errors.
  echo.
)

REM ---- 8. Open browser ----
echo.
echo ==============================================
echo   Game URL: %GAME_URL%
echo   Mode:     MOCK (NPC reactions are scripted)
echo   To stop:  Close the "G1N-Client" window
echo ==============================================
echo.
start "" "%GAME_URL%"
echo Game opened in your browser.
echo.
timeout /t 3 /nobreak >nul
exit /b 0
