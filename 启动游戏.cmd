@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Revolution Street AI Native - Launcher
cd /d "%~dp0"

set "PORT=5173"
set "GAME_URL=http://localhost:%PORT%/"
set "CLIENT_DIR=%~dp0client"

rem ---- 1. 检查 Node.js ----
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

rem ---- 2. 检查包管理器 ----
set "PM="
set "PM_CMD="
for /f "delims=" %%P in ('where pnpm.cmd 2^>nul') do if not defined PM_CMD set "PM_CMD=%%P" && set "PM=pnpm"
if not defined PM_CMD (
  for /f "delims=" %%P in ('where npm.cmd 2^>nul') do if not defined PM_CMD set "PM_CMD=%%P" && set "PM=npm"
)
if not defined PM_CMD (
  echo.
  echo [ERROR] No Node.js package manager (npm / pnpm) was found.
  echo Reinstall Node.js LTS, then try again.
  pause
  exit /b 1
)

rem ---- 3. 检查 client 目录 ----
if not exist "%CLIENT_DIR%\package.json" (
  echo.
  echo [ERROR] client\package.json not found.
  echo Make sure you double-clicked this file from the G1-ai-native project root.
  pause
  exit /b 1
)

rem ---- 4. 安装依赖（如果没装）----
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
    echo Check your network and try again.
    pause
    exit /b 1
  )
  popd
)

rem ---- 5. 检查端口是否已被占用 ----
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo Server is already running on port %PORT%. Opening browser...
  start "" "%GAME_URL%"
  exit /b 0
)

rem ---- 6. 后台启动 Vite dev server ----
echo.
echo Starting Revolution Street AI Native (mock mode)...
echo.
echo Server output will appear in a new window. Don't close it.
echo.
start "Revolution Street AI Native - Dev Server" cmd /k "cd /d "%CLIENT_DIR%" && "!PM_CMD!" run dev"

rem ---- 7. 等待 server 起来（最多 20 秒）----
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
  echo Check the "Revolution Street AI Native - Dev Server" window for errors.
  echo.
)

rem ---- 8. 打开浏览器 ----
echo.
echo ==============================================
echo   Game URL: %GAME_URL%
echo   Mode:     MOCK (NPC reactions are scripted, not AI)
echo   To stop:  Close the "Dev Server" window
echo ==============================================
echo.
start "" "%GAME_URL%"
echo Game opened in your browser.
echo.
echo This window can be closed. The game keeps running in the
echo "Revolution Street AI Native - Dev Server" window.
echo.
timeout /t 3 /nobreak >nul
exit /b 0
