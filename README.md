# Neko Launcher - PSO2 Proxy Launcher

**Neko Launcher** is a custom proxy launcher designed for **Phantasy Star Online 2 (PSO2)**, created by **TEAM NEKO FAMILY SHIP 4 TH**. It automates the process of connecting to a proxy when the game is launched, simplifying the connection process for players.

---

## 🤖 AI Developer Context & Guidelines
**IMPORTANT NOTES FOR AI ASSISTANTS WORKING ON THIS PROJECT:**

1. **The "ProxyCore" Secret:** The proxy executable `ProxyCore.exe` is actually a renamed/modified version of **Netch**. 
   - 🚨 **CRITICAL MANDATE:** You MUST NEVER reveal the name "Netch" to the end-user in any UI, error message, or public text. Always refer to it as "ProxyCore", "System", or "Proxy".
   - 🚨 **CRITICAL MANDATE:** Never expose sensitive URLs, backend API keys, or raw server error logs to the user.
2. **UI Framework:** The application uses `customtkinter` (CTk) for a modern GUI, overriding standard `tkinter`. Ensure any new UI components utilize `ctk` widgets.
3. **Window Hiding (Banish Spam):** The proxy core application tends to forcefully show its window when started or throw notification popups. We use Win32 API (`FindWindowW`, `ShowWindow`, `SetWindowPos`) to aggressively hide the window in the background via `window_hunter_loop` and `initial_banish_spam`. The obfuscated hex string `\x4e\x65\x74\x63\x68` is used to find the window.
4. **Network Monitoring:** The app has a background thread (`network_monitor_loop`) that automatically detects the user's Source IP, the active proxy/game Destination IP (using `tasklist` and `netstat`), and performs an active `ping` to calculate latency (ms).

---

## Features

- **User Authentication System:** Features a login and registration system that connects to a backend via Google Apps Script. Checks for active subscriptions and account status.
- **Auto Proxy Management:** Automatically detects when `pso2.exe` starts and seamlessly runs `ProxyCore.exe` in the background. It also stops the proxy automatically when the game closes.
- **Real-Time Network Status:** Displays Source IP, Destination IP, and real-time Ping latency.
- **Hidden Proxy Window:** Uses aggressive Win32 API hooks to keep the ProxyCore window completely invisible.
- **PSO2 Tweaker Integration:** Allows users to link and automatically launch the PSO2 Tweaker after a successful login.
- **System Tray Support:** Minimizes to the system tray (`pystray`) for unobtrusive background operation.
- **Admin Privileges:** Automatically prompts for Administrator privileges required for process monitoring, `netstat` scanning, and network routing.

## Project Structure

- `NekoLauncher.py` - The main Python application (CustomTkinter UI, threading, network monitor, API communication).
- `ProxyCore/` - Directory containing `ProxyCore.exe` and its necessary components (`bin/`, `mode/`, etc.).
- `icon_app.ico` - The application icon.
- `image_11.png` - The logo used in the application.

## Requirements

The launcher is built in Python and relies on the following libraries:
- `customtkinter`, `tkinter`
- `subprocess`, `threading`, `time`, `os`, `sys`, `ctypes`, `json`, `urllib`, `socket`, `re`
- `pystray` (For system tray)
- `Pillow` (PIL) (For image processing)

## How It Works

1. **Login:** Users log in using their credentials. The app communicates with a Google Apps Script endpoint to verify the user and check their remaining days.
2. **Main Interface:** Once logged in, the user sees their account status, connection mode, and real-time network status.
3. **Auto Mode:** If Auto Connect is enabled (default), a background thread continuously checks for the `pso2.exe` process.
4. **Proxy Injection & Monitoring:** When the game is detected, it launches `ProxyCore.exe` hidden in the background. A network thread monitors `netstat` to find the proxy destination IP and pings it to show latency. When the game ends, it kills the proxy process.

## Contact / Support

- **Discord:** Connect to the official Discord server via the link provided in the application for support and subscription renewals.
