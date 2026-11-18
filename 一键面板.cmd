@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem Open the graphical control panel (button-driven).

set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"

"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0deploy\panel.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Panel failed to start. Run manually:  pwsh -File deploy\panel.ps1
    pause
)
exit /b %RC%
