@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem One-click stop: release port 8000 and clean up leftover processes.

set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\stop-gateway.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
pause
exit /b %RC%
