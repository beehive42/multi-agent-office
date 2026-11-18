@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem One-click start: gateway -> readiness wait -> health check -> web console.
rem Arguments are forwarded to deploy\launch.ps1, e.g.  start.cmd -Demo

set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\launch.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [FAILED] exit code %RC%
) else (
    echo [OK] finished.
)
pause
exit /b %RC%
