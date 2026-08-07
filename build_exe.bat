@echo off
echo ===================================================
echo Building NekoLauncher Executable...
echo ===================================================

cd /d "%~dp0launcher"
uv run python -m PyInstaller --clean --noconfirm NekoLauncher.spec

echo.
echo ===================================================
echo Build Process Finished!
echo Check the 'launcher\dist' folder for NekoLauncher.exe
echo ===================================================
pause
