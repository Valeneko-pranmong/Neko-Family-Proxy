# Neko Launcher - PSO2 Proxy Launcher

**Neko Launcher** is a custom proxy launcher designed for **Phantasy Star Online 2 (PSO2)**, created by **TEAM NEKO FAMILY SHIP 4 TH**. It automates the process of starting and stopping a proxy (using Netch) when the game is launched, simplifying the connection process for players.

## Features

- **User Authentication System:** Features a login and registration system that connects to a backend via Google Apps Script. Checks for active subscriptions and account status.
- **Auto Proxy Management:** Automatically detects when `pso2.exe` starts and seamlessly runs the proxy (`Netch.exe`) in the background. It also stops the proxy automatically when the game closes.
- **Hidden Proxy Window:** Uses Win32 API to hide the Netch proxy window to prevent desktop clutter.
- **PSO2 Tweaker Integration:** Allows users to link and automatically launch the PSO2 Tweaker after a successful login.
- **System Tray Support:** Minimizes to the system tray for unobtrusive background operation.
- **Admin Privileges:** Automatically prompts for Administrator privileges required for process monitoring and network routing.

## Project Structure

- `NekoLauncher.py` - The main Python application (Tkinter UI, background monitoring, API communication).
- `Netch/` - Directory containing the Netch proxy application and its necessary components (`bin/`, `mode/`, etc.).
- `icon_app.ico` - The application icon.
- `image_11.png` - The logo used in the application.

## Requirements

The launcher is built in Python and relies on the following libraries:
- `tkinter` (Built-in)
- `subprocess`, `threading`, `time`, `os`, `sys`, `ctypes`, `json`, `urllib`
- `pystray` (For system tray)
- `Pillow` (PIL) (For image processing)

## How It Works

1. **Login:** Users log in using their credentials. The app communicates with a Google Apps Script endpoint to verify the user and check their remaining days.
2. **Main Interface:** Once logged in, the user sees their account status and proxy settings.
3. **Auto Mode:** If Auto Connect is enabled (default), a background thread continuously checks for the `pso2.exe` process.
4. **Proxy Injection:** When the game is detected, it launches `Netch/Netch.exe` hidden in the background. When the game ends, it kills the proxy process.

## Contact / Support

- **Discord:** Connect to the official Discord server via the link provided in the application for support and subscription renewals.
