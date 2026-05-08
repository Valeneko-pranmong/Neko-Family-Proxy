import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog
import subprocess
import threading
import time
import os
import sys
import ctypes
import webbrowser
import json 
import urllib.request
import urllib.error
from datetime import datetime

import pystray
from PIL import Image as PILImage
from pystray import MenuItem as item

# ==========================================
# 🔧 Fix Icon Taskbar
# ==========================================
try:
    myappid = 'neko.family.launcher.proxy.v1'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except: pass

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ==========================================
# Config
# ==========================================
APP_VERSION = "4.0.2 Release" # ปรับเป็น 4.0.2 (CTk UI Update)
SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzBCPV1kfJ54HJnK03MAgr09dkEg2mipaAYRQhrue68q5gpF0u_8S-ioh7p74umAUo6/exec"
DISCORD_LINK = "https://discord.gg/fkjXW9AJ6a"

NETCH_EXE = resource_path(os.path.join("Netch", "Netch.exe"))
LOGO_IMAGE = resource_path("image_11.png") 
ICON_APP = resource_path("icon_app.ico")
GAME_EXE = "pso2.exe"
REFRESH_RATE = 2 

try:
    app_data_dir = os.path.join(os.environ["LOCALAPPDATA"], "NEKO FAMILY")
    if not os.path.exists(app_data_dir):
        os.makedirs(app_data_dir)
    USER_CACHE_FILE = os.path.join(app_data_dir, "login_data.json")
except Exception as e:
    USER_CACHE_FILE = "login_data.json"

# Theme CTk
ctk.set_appearance_mode("light")

BG_MAIN = "#FFF0F5"          
BG_BOX = "#FFFFFF"           
BG_STATUS = "#FFE4E1"        
TEXT_MAIN = "#555555"        
TEXT_HEADER = "#FF1493"      
TEXT_HIGHLIGHT = "#FF69B4"   
TEXT_GOLD = "#FFA07A"        
BTN_COLOR = "#FFB6C1"        
BTN_HOVER = "#FF69B4"
BTN_TEXT = "#FFFFFF"         
BTN_DISABLED = "#E0E0E0"     
STATUS_RED = "#FF6347"       
STATUS_GREEN = "#32CD32"     

# Win32 API
user32 = ctypes.windll.user32
SW_HIDE = 0
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
LWA_ALPHA = 0x2

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

def banish_netch_window():
    try:
        hwnd = user32.FindWindowW(None, "Netch")
        if hwnd:
            user32.SetWindowPos(hwnd, 0, -20000, -20000, 0, 0, 0x0015)
            if user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_HIDE)
            ex_style = user32.GetWindowLongA(hwnd, GWL_EXSTYLE)
            if not (ex_style & WS_EX_LAYERED):
                user32.SetWindowLongA(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
            return True
    except: pass
    return False

def is_game_running(process_name):
    try:
        cmd = f'tasklist /FI "IMAGENAME eq {process_name}" /NH'
        output = subprocess.check_output(cmd, creationflags=subprocess.CREATE_NO_WINDOW).decode('latin-1')
        return process_name.lower() in output.lower()
    except:
        return False

def send_data(payload):
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(SCRIPT_URL, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8').strip()
    except Exception as e:
        return f"Error: {e}"

# Login App
class LoginApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Neko Launcher - Login | {APP_VERSION}") 
        self.root.geometry("340x480") 
        self.root.resizable(False, False) 
        
        self.root.configure(fg_color=BG_MAIN)
        try: self.root.iconbitmap(ICON_APP)
        except: pass
        
        self.root.bind('<Return>', lambda event: self.check_login())
        
        main_frame = ctk.CTkFrame(self.root, fg_color=BG_BOX, corner_radius=15)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(main_frame, text="NEKO LOGIN", font=ctk.CTkFont(family="Arial", size=22, weight="bold"), text_color=TEXT_HEADER).pack(pady=(15, 15))
        
        ctk.CTkLabel(main_frame, text="Username:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).pack(anchor="w", padx=15)
        self.entry_user = ctk.CTkEntry(main_frame, font=ctk.CTkFont(family="Arial", size=12), fg_color="white", text_color=TEXT_MAIN, border_color=BTN_COLOR, border_width=2, corner_radius=8)
        self.entry_user.pack(fill="x", padx=15, pady=(0, 10), ipady=3)

        ctk.CTkLabel(main_frame, text="Password:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).pack(anchor="w", padx=15)
        self.entry_pass = ctk.CTkEntry(main_frame, show="*", font=ctk.CTkFont(family="Arial", size=12), fg_color="white", text_color=TEXT_MAIN, border_color=BTN_COLOR, border_width=2, corner_radius=8)
        self.entry_pass.pack(fill="x", padx=15, pady=(0, 15), ipady=3)

        self.btn_login = ctk.CTkButton(main_frame, text="Login & Start", command=self.check_login, 
                  fg_color=BTN_COLOR, hover_color=BTN_HOVER, text_color=BTN_TEXT, font=ctk.CTkFont(family="Arial", size=14, weight="bold"), corner_radius=8)
        self.btn_login.pack(fill="x", padx=15, pady=10, ipady=3)

        self.btn_reg_link = ctk.CTkButton(main_frame, text="สมัครสมาชิก (Register)", command=self.open_register, 
                  fg_color="transparent", hover_color=BG_MAIN, text_color=TEXT_HIGHLIGHT, font=ctk.CTkFont(family="Arial", size=12))
        self.btn_reg_link.pack(pady=2)

        self.status_label = ctk.CTkLabel(main_frame, text="", font=ctk.CTkFont(family="Arial", size=12, weight="bold"), text_color=STATUS_RED)
        self.status_label.pack(pady=5)
        
        link_label = ctk.CTkLabel(main_frame, text="ติดต่อแจ้งปัญหา / เติมวัน (Discord)", font=ctk.CTkFont(family="Arial", size=11), text_color="#5865F2", cursor="hand2")
        link_label.pack(side="bottom", pady=10) 
        link_label.bind("<Button-1>", lambda e: webbrowser.open(DISCORD_LINK))

        self.attempt_auto_login()

    def attempt_auto_login(self):
        try:
            if os.path.exists(USER_CACHE_FILE):
                with open(USER_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved_user = data.get("username", "")
                    saved_pass = data.get("password", "")
                    
                    if saved_user and saved_pass:
                        self.entry_user.insert(0, saved_user)
                        self.entry_pass.insert(0, saved_pass)
                        
                        self.btn_login.configure(state="disabled")
                        self.btn_reg_link.configure(state="disabled")
                        
                        self.status_label.configure(text="กำลังเข้าสู่ระบบอัตโนมัติ...", text_color=TEXT_HIGHLIGHT)
                        self.root.after(800, self.check_login) 
        except: pass

    def save_credentials(self, username, password):
        try:
            data = {}
            if os.path.exists(USER_CACHE_FILE):
                with open(USER_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            
            data["username"] = username
            data["password"] = password
            
            with open(USER_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except: pass

    def check_login(self):
        self.btn_login.configure(state="disabled")
        self.btn_reg_link.configure(state="disabled")
        self.status_label.configure(text="กำลังตรวจสอบ... (Checking...)", text_color=TEXT_MAIN)
        self.root.update()

        user = self.entry_user.get().strip()
        pwd = self.entry_pass.get().strip()
        
        if not user or not pwd:
            self.status_label.configure(text="กรุณาใส่ Username และ Password ให้ครบถ้วน!", text_color=STATUS_RED)
            self.btn_login.configure(state="normal")
            self.btn_reg_link.configure(state="normal")
            return

        self.status_label.configure(text="กำลังเชื่อมต่อ... (Connecting)", text_color=TEXT_HIGHLIGHT)
        self.root.update()
        threading.Thread(target=self._do_login_thread, args=(user, pwd)).start()

    def _do_login_thread(self, user, pwd):
        result = send_data({"action": "login", "username": user, "password": pwd})
        self.root.after(0, self._post_login, result, user, pwd)

    def _post_login(self, result, user, pwd):
        if result.startswith("OK"):
            self.save_credentials(user, pwd)
            parts = result.split("|")
            expiry_date = parts[1] if len(parts) > 1 else "Unknown"
            
            self.root.destroy()
            open_main_launcher(user, expiry_date)
        else:
            self.btn_login.configure(state="normal")
            self.btn_reg_link.configure(state="normal")
            
            if result == "EXPIRED":
                self.status_label.configure(text="วันหมดอายุแล้ว! โปรดติดต่อแอดมิน", text_color=STATUS_RED)
            elif result == "BANNED":
                self.status_label.configure(text="บัญชีนี้ถูกระงับ! โปรดติดต่อแอดมิน", text_color=STATUS_RED)
            elif result == "FAIL":
                self.status_label.configure(text="Username หรือ Password ไม่ถูกต้อง!", text_color=STATUS_RED)
            else:
                self.status_label.configure(text=f"เชื่อมต่อล้มเหลว: {result}", text_color=STATUS_RED)

    def open_register(self):
        reg_win = ctk.CTkToplevel(self.root)
        reg_win.title(f"Register | {APP_VERSION}") 
        reg_win.geometry("340x550") 
        reg_win.resizable(False, False) 
        reg_win.transient(self.root)
        
        reg_win.configure(fg_color=BG_MAIN)
        try: reg_win.iconbitmap(ICON_APP)
        except: pass
        
        reg_frame = ctk.CTkFrame(reg_win, fg_color=BG_BOX, corner_radius=15)
        reg_frame.pack(pady=20, padx=20, fill="both", expand=True)
        
        ctk.CTkLabel(reg_frame, text="REGISTER", font=ctk.CTkFont(family="Arial", size=20, weight="bold"), text_color=TEXT_HEADER).pack(pady=(15, 10))
        
        ctk.CTkLabel(reg_frame, text="Username:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).pack(anchor="w", padx=15)
        r_user = ctk.CTkEntry(reg_frame, font=ctk.CTkFont(family="Arial", size=12), fg_color="white", text_color=TEXT_MAIN, border_color=BTN_COLOR, border_width=2, corner_radius=8)
        r_user.pack(fill="x", padx=15, pady=(0, 10), ipady=3)
        
        ctk.CTkLabel(reg_frame, text="Password:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).pack(anchor="w", padx=15)
        r_pass = ctk.CTkEntry(reg_frame, show="*", font=ctk.CTkFont(family="Arial", size=12), fg_color="white", text_color=TEXT_MAIN, border_color=BTN_COLOR, border_width=2, corner_radius=8)
        r_pass.pack(fill="x", padx=15, pady=(0, 10), ipady=3)
        
        ctk.CTkLabel(reg_frame, text="Confirm Password:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).pack(anchor="w", padx=15)
        r_conf = ctk.CTkEntry(reg_frame, show="*", font=ctk.CTkFont(family="Arial", size=12), fg_color="white", text_color=TEXT_MAIN, border_color=BTN_COLOR, border_width=2, corner_radius=8)
        r_conf.pack(fill="x", padx=15, pady=(0, 10), ipady=3)

        reg_status = ctk.CTkLabel(reg_frame, text="", font=ctk.CTkFont(family="Arial", size=11), text_color=STATUS_RED)
        reg_status.pack(pady=2)

        btn_do_reg = ctk.CTkButton(reg_frame, text="Register", fg_color=BTN_COLOR, hover_color=BTN_HOVER, text_color=BTN_TEXT, font=ctk.CTkFont(family="Arial", size=14, weight="bold"), corner_radius=8)
        
        def do_reg():
            u = r_user.get().strip()
            p = r_pass.get().strip()
            c = r_conf.get().strip()
            if not u or not p: 
                reg_status.configure(text="กรุณาใส่ข้อมูลให้ครบ", text_color=STATUS_RED)
                return
            if p != c:
                reg_status.configure(text="รหัสผ่านไม่ตรงกัน", text_color=STATUS_RED)
                return
            
            btn_do_reg.configure(state="disabled")
            reg_status.configure(text="กำลังสมัครสมาชิก...", text_color=TEXT_MAIN)
            threading.Thread(target=lambda: _process_reg(u, p)).start()
            
        def _process_reg(u, p):
            resp = send_data({"action": "register", "username": u, "password": p})
            reg_win.after(0, lambda: _finish_reg(resp))
            
        def _finish_reg(resp):
            if resp == "REGISTER_SUCCESS":
                self.root.clipboard_clear()
                self.root.clipboard_append(DISCORD_LINK)
                webbrowser.open(DISCORD_LINK) 
                messagebox.showinfo("ยินดีด้วย!", "สมัครเรียบร้อยวัยรุ่น!\nเดี๋ยวพี่พาไป Discord ทักแอดมินเติมวันได้เลย!")
                reg_win.destroy()
            else:
                btn_do_reg.configure(state="normal")
                if resp == "DUPLICATE":
                    reg_status.configure(text="ชื่อนี้มีคนใช้แล้ว เปลี่ยนชื่อใหม่!", text_color=STATUS_RED)
                else:
                    reg_status.configure(text=f"เกิดข้อผิดพลาด: {resp}", text_color=STATUS_RED)
        
        btn_do_reg.configure(command=do_reg)
        btn_do_reg.pack(fill="x", padx=15, pady=10, ipady=3)
        
        disc_label = ctk.CTkLabel(reg_frame, text="ติดต่อแจ้งปัญหา / เติมวัน (Discord)", font=ctk.CTkFont(family="Arial", size=11), text_color="#5865F2", cursor="hand2")
        disc_label.pack(side="bottom", pady=2)
        disc_label.bind("<Button-1>", lambda e: webbrowser.open(DISCORD_LINK))

        ctk.CTkLabel(reg_frame, text="*สมัครแล้วต้องแจ้งแอดมินเพื่อเติมวัน*", font=ctk.CTkFont(family="Arial", size=11), text_color=TEXT_HIGHLIGHT).pack(side="bottom", pady=2)

# Main App
class NekoLauncher:
    def __init__(self, root, username, expiry_date):
        self.root = root
        self.username = username
        self.expiry_date = expiry_date
        
        self.config_data = self.load_config()
        self.root.title(f"NEKO FAMILY TEAM SHOP - PROXY LAUNCHER | {APP_VERSION}")
        
        # Window size
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        window_width = 540
        calculated_height = int(screen_height * 0.85)
        window_height = min(730, calculated_height) 

        center_x = int((screen_width - window_width) / 2)
        center_y = int((screen_height - window_height) / 2)

        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        self.root.resizable(False, False)
        
        self.root.configure(fg_color=BG_MAIN)
        
        try: self.root.iconbitmap(ICON_APP)
        except: pass
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Unmap>", self.check_minimize_event)
        self.tray_icon = None
        self.notified_tray = False

        self.is_auto = tk.BooleanVar(value=True)
        self.proxy_running = False
        self.game_running = False
        self.running = True
        self.logo_img = None
        self.load_logo()
        
        self.create_ui()
        
        if self.auto_tweaker_var.get() and self.tweaker_path_var.get():
            self.root.after(1000, self.launch_tweaker)

        self.monitor_thread = threading.Thread(target=self.system_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        self.hunter_thread = threading.Thread(target=self.window_hunter_loop)
        self.hunter_thread.daemon = True
        self.hunter_thread.start()

    def load_config(self):
        try:
            if os.path.exists(USER_CACHE_FILE):
                with open(USER_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except: pass
        return {}

    def save_config_key(self, key, value):
        data = self.load_config()
        data[key] = value
        try:
            with open(USER_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except: pass

    def check_minimize_event(self, event):
        if event.widget == self.root and self.root.state() == 'iconic':
            self.hide_to_tray()

    def hide_to_tray(self):
        self.root.withdraw() 
        image = PILImage.open(ICON_APP)
        menu = (item('Show', self.show_from_tray, default=True), 
                item('Exit', self.quit_app))
        self.tray_icon = pystray.Icon("neko_launcher", image, "Neko Launcher", menu)
        
        def run_tray():
            self.tray_icon.run()
            
        threading.Thread(target=run_tray, daemon=True).start()
        
        if not self.notified_tray:
            self.root.after(500, self.show_tray_notification)
            self.notified_tray = True
            
    def show_tray_notification(self):
        try:
            if self.tray_icon and self.tray_icon.HAS_NOTIFICATION:
                self.tray_icon.notify("Neko Launcher is still running in the background", "Neko Launcher")
        except: pass

    def show_from_tray(self, icon, item):
        self.tray_icon.stop() 
        self.root.deiconify() 

    def quit_app(self, icon, item):
        self.tray_icon.stop()
        self.on_close() 

    def load_logo(self):
        try:
            if os.path.exists(LOGO_IMAGE): 
                pil_img = PILImage.open(LOGO_IMAGE)
                self.logo_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(pil_img.width, pil_img.height))
        except: pass

    def create_ui(self):
        # 1. แถบ Status ด้านล่างสุด
        status_frame = ctk.CTkFrame(self.root, fg_color=BG_STATUS, corner_radius=0)
        status_frame.pack(side="bottom", fill="x") 
        
        status_frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(status_frame, text="Proxy Status:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=5, padx=(20, 10))
        self.lbl_proxy_status = ctk.CTkLabel(status_frame, text="ไม่ได้ใช้งาน (Inactive)", font=ctk.CTkFont(family="Arial", size=14, weight="bold"), text_color=STATUS_RED)
        self.lbl_proxy_status.grid(row=0, column=1, sticky="w", pady=5)
        
        ctk.CTkLabel(status_frame, text="Game Status:", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN).grid(row=1, column=0, sticky="w", pady=5, padx=(20, 10))
        self.lbl_game_status = ctk.CTkLabel(status_frame, text="ไม่พบ process เกม", font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_HIGHLIGHT)
        self.lbl_game_status.grid(row=1, column=1, sticky="w", pady=5)
        
        link_label = ctk.CTkLabel(status_frame, text="ติดต่อแจ้งปัญหา / เติมวัน (Discord)", font=ctk.CTkFont(family="Arial", size=11), text_color="#5865F2", cursor="hand2")
        link_label.grid(row=2, column=0, columnspan=2, pady=(5, 10))
        link_label.bind("<Button-1>", lambda e: webbrowser.open(DISCORD_LINK))

        # 2. พื้นที่เนื้อหาหลัก
        main_content = ctk.CTkFrame(self.root, fg_color=BG_MAIN, corner_radius=0)
        main_content.pack(side="top", fill="both", expand=True) 
        
        wrapper = ctk.CTkScrollableFrame(main_content, fg_color=BG_MAIN)
        wrapper.pack(expand=True, fill="both", padx=10, pady=10) 

        header_frame = ctk.CTkFrame(wrapper, fg_color=BG_MAIN)
        header_frame.pack(pady=(10, 10))
        
        if self.logo_img:
            ctk.CTkLabel(header_frame, image=self.logo_img, text="").pack(pady=(0, 5))
        else:
            ctk.CTkLabel(header_frame, text="NEKO FAMILY", font=ctk.CTkFont(family="Arial", size=24, weight="bold"), text_color=TEXT_HEADER).pack()
            
        ctk.CTkLabel(header_frame, text="High Performance PSO2 Proxy Created By TEAM NEKO FAMILY", 
                 font=ctk.CTkFont(family="Arial", size=11), text_color=TEXT_HIGHLIGHT).pack(pady=2)
                 
        days_str = "??"
        try:
            exp = datetime.strptime(self.expiry_date, "%Y-%m-%d").date()
            now = datetime.now().date()
            days_left = (exp - now).days
            days_str = str(max(0, days_left))
        except: pass
        
        info_frame = ctk.CTkFrame(wrapper, fg_color=BG_BOX, corner_radius=10, border_color=BTN_COLOR, border_width=1)
        info_frame.pack(pady=5, padx=20, fill="x")
        info_text = f"ผู้ใช้งาน: {self.username}  |  เหลือ: {days_str} วัน (หมด: {self.expiry_date})"
        ctk.CTkLabel(info_frame, text=info_text, font=ctk.CTkFont(family="Arial", size=12, weight="bold"), text_color=TEXT_GOLD).pack(pady=10, padx=10)
        
        settings_box = ctk.CTkFrame(wrapper, fg_color=BG_BOX, corner_radius=15)
        settings_box.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(settings_box, text="ตั้งค่าการเชื่อมต่อ (Connection Mode)", font=ctk.CTkFont(family="Arial", size=14, weight="bold"), text_color=TEXT_HEADER).pack(anchor="w", padx=15, pady=(15, 5))
        self.chk_auto = ctk.CTkCheckBox(settings_box, text="เชื่อมต่อโดยอัตโนมัติ เมื่อเริ่มเกม (Auto Connect)", 
                       variable=self.is_auto, font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN, 
                       fg_color=BTN_COLOR, hover_color=TEXT_HIGHLIGHT, border_color=BTN_COLOR,
                       command=self.update_button_state, cursor="hand2")
        self.chk_auto.pack(anchor="w", padx=20, pady=10)
        
        divider = ctk.CTkFrame(settings_box, height=1, fg_color=BTN_COLOR)
        divider.pack(fill="x", padx=15, pady=5)
        
        ctk.CTkLabel(settings_box, text="ควบคุมด้วยตนเอง (Manual Control)", font=ctk.CTkFont(family="Arial", size=14, weight="bold"), text_color=TEXT_HEADER).pack(anchor="w", padx=15, pady=(5, 5))
        
        self.btn_manual = ctk.CTkButton(settings_box, text="START PROXY", font=ctk.CTkFont(family="Arial", size=14, weight="bold"), 
                                    fg_color=BTN_DISABLED, text_color=BTN_TEXT, state="disabled", 
                                    command=self.toggle_manual, corner_radius=8, cursor="hand2")
        self.btn_manual.pack(fill="x", padx=15, pady=(5, 15), ipady=3)
        
        tweaker_box = ctk.CTkFrame(wrapper, fg_color=BG_BOX, corner_radius=15)
        tweaker_box.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(tweaker_box, text="ตั้งค่าเข้าเกม (PSO2 Tweaker)", font=ctk.CTkFont(family="Arial", size=14, weight="bold"), text_color=TEXT_HEADER).pack(anchor="w", padx=15, pady=(15, 5))
        
        self.tweaker_path_var = tk.StringVar(value=self.config_data.get("tweaker_path", ""))
        self.auto_tweaker_var = tk.BooleanVar(value=self.config_data.get("auto_tweaker", False))
        
        path_frame = ctk.CTkFrame(tweaker_box, fg_color="transparent")
        path_frame.pack(fill="x", padx=15, pady=5)
        
        self.lbl_tpath = ctk.CTkLabel(path_frame, textvariable=self.tweaker_path_var, font=ctk.CTkFont(family="Arial", size=11), fg_color=BG_STATUS, text_color=TEXT_MAIN, anchor="w", corner_radius=5)
        self.lbl_tpath.pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 10))
        
        btn_browse = ctk.CTkButton(path_frame, text="เลือกไฟล์ (Browse)", width=100, font=ctk.CTkFont(family="Arial", size=11), fg_color=TEXT_GOLD, hover_color="#F4A460", text_color=BTN_TEXT, command=self.browse_tweaker, corner_radius=5, cursor="hand2")
        btn_browse.pack(side="right")
        
        self.chk_auto_tweaker = ctk.CTkCheckBox(tweaker_box, text="เปิด Tweaker อัตโนมัติเมื่อล็อคอินสำเร็จ", 
                       variable=self.auto_tweaker_var, font=ctk.CTkFont(family="Arial", size=12), text_color=TEXT_MAIN, 
                       fg_color=BTN_COLOR, hover_color=TEXT_HIGHLIGHT, border_color=BTN_COLOR,
                       command=self.save_tweaker_settings, cursor="hand2")
        self.chk_auto_tweaker.pack(anchor="w", padx=20, pady=10)
                       
        btn_launch = ctk.CTkButton(tweaker_box, text="เปิดโปรแกรม PSO2 Tweaker", font=ctk.CTkFont(family="Arial", size=13, weight="bold"), fg_color=BTN_COLOR, hover_color=BTN_HOVER, text_color=BTN_TEXT, command=self.launch_tweaker, corner_radius=8, cursor="hand2")
        btn_launch.pack(fill="x", padx=15, pady=(5, 15), ipady=3)

    def browse_tweaker(self):
        path = filedialog.askopenfilename(title="เลือกไฟล์ PSO2 Tweaker.exe", filetypes=[("Executable Files", "*.exe")])
        if path:
            self.tweaker_path_var.set(path)
            self.save_tweaker_settings() 

    def save_tweaker_settings(self):
        self.save_config_key("tweaker_path", self.tweaker_path_var.get())
        self.save_config_key("auto_tweaker", self.auto_tweaker_var.get())

    def launch_tweaker(self):
        path = self.tweaker_path_var.get()
        if os.path.exists(path):
            try:
                subprocess.Popen(path, cwd=os.path.dirname(path))
            except Exception as e:
                messagebox.showerror("Error", f"เปิด Tweaker ไม่สำเร็จ:\n{e}")
        else:
            if path: 
                messagebox.showwarning("เตือน", "หาไฟล์ Tweaker ไม่เจอ กรุณากดปุ่ม Browse เพื่อเลือกไฟล์ใหม่ครับ")
            else:
                messagebox.showwarning("เตือน", "กรุณาเลือกไฟล์ PSO2 Tweaker ก่อนครับ")

    def update_button_state(self):
        if self.is_auto.get() or self.game_running:
            self.btn_manual.configure(state="disabled", fg_color=BTN_DISABLED, text="Auto Mode Active...")
        else:
            self.btn_manual.configure(state="normal", fg_color=BTN_COLOR, text="START PROXY")
            if self.proxy_running: self.btn_manual.configure(text="STOP PROXY", fg_color=STATUS_RED, hover_color="#CD5C5C")

    def toggle_manual(self):
        if self.proxy_running: self.stop_netch()
        else: self.start_netch()
        self.update_button_state()

    def system_loop(self):
        while self.running:
            self.game_running = is_game_running(GAME_EXE)
            if self.is_auto.get():
                if self.game_running and not self.proxy_running:
                    self.start_netch()
                elif not self.game_running and self.proxy_running:
                    self.stop_netch()
            self.root.after(0, self.update_status_ui)
            time.sleep(REFRESH_RATE)

    def window_hunter_loop(self):
        while self.running:
            if self.proxy_running:
                banish_netch_window()
                time.sleep(0.02)
            else:
                time.sleep(1)

    def start_netch(self):
        if self.proxy_running: return
        try:
            target_path = NETCH_EXE
            if not os.path.exists(target_path) and os.path.exists("Netch.exe"): target_path = "Netch.exe"
            
            if os.path.exists(target_path):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 
                
                netch_dir = os.path.dirname(os.path.abspath(target_path))
                
                subprocess.Popen(target_path, cwd=netch_dir, startupinfo=startupinfo)
                self.proxy_running = True
                threading.Thread(target=self.initial_banish_spam).start()
            else:
                print("Netch not found")
        except Exception as e:
            print(f"Error: {e}")

    def initial_banish_spam(self):
        for _ in range(50): 
            if not self.running: break
            banish_netch_window()
            time.sleep(0.05)

    def stop_netch(self):
        if not self.proxy_running: return
        exe_name = os.path.basename(NETCH_EXE)
        subprocess.run(f"taskkill /IM {exe_name}", shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(f"taskkill /F /IM {exe_name}", shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.proxy_running = False

    def update_status_ui(self):
        if self.proxy_running:
            self.lbl_proxy_status.configure(text="กำลังทำงาน (Active)", text_color=STATUS_GREEN)
        else:
            self.lbl_proxy_status.configure(text="ไม่ได้ใช้งาน (Inactive)", text_color=STATUS_RED)
        if self.game_running:
            self.lbl_game_status.configure(text=f"ตรวจพบเกม ({GAME_EXE})", text_color=STATUS_GREEN)
        else:
            self.lbl_game_status.configure(text=f"ไม่พบ process เกม", text_color=TEXT_HIGHLIGHT)
        self.update_button_state()

    def on_close(self):
        self.running = False
        self.stop_netch()
        self.root.destroy()
        sys.exit()

def open_main_launcher(username, expiry_date):
    root = ctk.CTk()
    app = NekoLauncher(root, username, expiry_date)
    root.mainloop()

if __name__ == "__main__":
    if not is_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        except: messagebox.showerror("Error", "Need Admin Rights")
        sys.exit()
    root = ctk.CTk()
    app = LoginApp(root)
    root.mainloop()
