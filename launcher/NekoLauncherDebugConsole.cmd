@echo off
chcp 65001 >nul
title Neko Family - Live Debug Console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\debug_console.ps1" -LauncherPath "%~dp0dist\NekoLauncher.exe"
echo.
echo Press any key to close this console.
pause >nul
