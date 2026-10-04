@echo off
setlocal
cd /d "%~dp0"
docker compose -p nos-deniers-plfss-local up -d --build --wait --wait-timeout 180 web
if errorlevel 1 (
  echo Le demarrage PLFSS a echoue. Les autres applications ne sont pas modifiees.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:18895/"
