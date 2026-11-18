@echo off
setlocal
set "ROOT=%~dp0"
set "PATH=%ROOT%tools\node;%ROOT%tools\npm-global;%PATH%"
set "OPENCLAW_HOME=%ROOT:~0,-1%"
call "%ROOT%tools\npm-global\openclaw.cmd" %*
exit /b %ERRORLEVEL%
