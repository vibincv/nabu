@echo off
rem Start Nabu (beta) on Windows: double-click this file, or run "start-nabu.cmd -Setup" etc.
rem It runs start-nabu.ps1 with the same options, without changing PowerShell's script policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-nabu.ps1" %*
set RC=%ERRORLEVEL%
rem Keep the window open on failure so the message can be read (double-click closes it otherwise).
if not "%RC%"=="0" pause
exit /b %RC%
