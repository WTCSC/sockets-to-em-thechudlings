import asyncio
import re
import subprocess
import base64
import io
import json
import mimetypes
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, simpledialog
from PIL import Image, ImageTk, ImageSequence
import platform

# macOS tk.Button ignores bg colors; use tkmacosx if available
if platform.system() == "Darwin":
    try:
        from tkmacosx import Button as tkButton
    except ImportError:
        tkButton = tk.Button
else:
    tkButton = tk.Button

import hashlib
import uuid
import websockets
import tempfile
import shutil

DEFAULT_URL = "ws://localhost:8080"
CHUDSERVE_URL = "wss://mediastation.tail76b4d2.ts.net"
CHANNELS = ["General", "Testing", "ChudSpeaks"]
SESSION_FILE = ".chud_session"

# Theme definitions
THEMES = {
    "Dark": {
        "bg_primary": "#1E1E2E",      # Main background
        "bg_secondary": "#181825",   # Sidebar, chat area
        "bg_tertiary": "#11111B",    # Footer, inputs
        "bg_accent": "#313244",      # Buttons, entries
        "fg_primary": "#CDD6F4",     # Main text
        "fg_secondary": "#A6ADC8",   # Secondary text
        "fg_accent": "#89B4FA",      # Links, highlights
        "fg_sender_me": "#89B4FA",   # My messages
        "fg_sender_other": "#A6E3A1", # Others' messages
        "fg_mention": "#FAB387",     # Mentions background
        "fg_info": "#585B70",        # Info messages
        "fg_timestamp": "#45475A",   # Timestamps
        "btn_primary": "#89B4FA",    # Primary buttons
        "btn_secondary": "#313244",  # Secondary buttons
        "btn_danger": "#F38BA8",     # Danger buttons
        "border": "#45475A",         # Borders
        "font_family": "Arial",
        "font_size": 14
    },
    "Light": {
        "bg_primary": "#FFFFFF",     # Main background
        "bg_secondary": "#F8F9FA",   # Sidebar, chat area
        "bg_tertiary": "#E9ECEF",    # Footer, inputs
        "bg_accent": "#DEE2E6",      # Buttons, entries
        "fg_primary": "#212529",     # Main text
        "fg_secondary": "#6C757D",   # Secondary text
        "fg_accent": "#007BFF",      # Links, highlights
        "fg_sender_me": "#007BFF",   # My messages
        "fg_sender_other": "#28A745", # Others' messages
        "fg_mention": "#FFC107",     # Mentions background
        "fg_info": "#6C757D",        # Info messages
        "fg_timestamp": "#ADB5BD",   # Timestamps
        "btn_primary": "#007BFF",    # Primary buttons
        "btn_secondary": "#6C757D",  # Secondary buttons
        "btn_danger": "#DC3545",     # Danger buttons
        "border": "#DEE2E6",         # Borders
        "font_family": "Segoe UI",
        "font_size": 14
    },
    "Neon": {
        "bg_primary": "#0D0D0D",     # Main background
        "bg_secondary": "#1A1A1A",   # Sidebar, chat area
        "bg_tertiary": "#2A2A2A",    # Footer, inputs
        "bg_accent": "#3A3A3A",      # Buttons, entries
        "fg_primary": "#00FF88",     # Main text
        "fg_secondary": "#00CCFF",   # Secondary text
        "fg_accent": "#FF0080",      # Links, highlights
        "fg_sender_me": "#FF0080",   # My messages
        "fg_sender_other": "#00FF88", # Others' messages
        "fg_mention": "#FFFF00",     # Mentions background
        "fg_info": "#888888",        # Info messages
        "fg_timestamp": "#666666",   # Timestamps
        "btn_primary": "#FF0080",    # Primary buttons
        "btn_secondary": "#3A3A3A",  # Secondary buttons
        "btn_danger": "#FF4444",     # Danger buttons
        "border": "#555555",         # Borders
        "font_family": "Courier New",
        "font_size": 12
    },
    "Retro": {
        "bg_primary": "#2B2B2B",     # Main background
        "bg_secondary": "#1F1F1F",   # Sidebar, chat area
        "bg_tertiary": "#3F3F3F",    # Footer, inputs
        "bg_accent": "#4F4F4F",      # Buttons, entries
        "fg_primary": "#F0F0F0",     # Main text
        "fg_secondary": "#CCCCCC",   # Secondary text
        "fg_accent": "#FFD700",      # Links, highlights
        "fg_sender_me": "#FFD700",   # My messages
        "fg_sender_other": "#98FB98", # Others' messages
        "fg_mention": "#FFA500",     # Mentions background
        "fg_info": "#808080",        # Info messages
        "fg_timestamp": "#A0A0A0",   # Timestamps
        "btn_primary": "#FFD700",    # Primary buttons
        "btn_secondary": "#4F4F4F",  # Secondary buttons
        "btn_danger": "#FF6347",     # Danger buttons
        "border": "#606060",         # Borders
        "font_family": "Consolas",
        "font_size": 13
    },
    "Crazy Pink": {
        "bg_primary": "#FF1493",      # Hot pink main background
        "bg_secondary": "#FF69B4",    # Hot pink sidebar, chat area
        "bg_tertiary": "#FFB6C1",     # Light pink footer, inputs
        "bg_accent": "#FFC0CB",       # Pink buttons, entries
        "fg_primary": "#FFFF00",      # Bright yellow main text
        "fg_secondary": "#00FFFF",    # Cyan secondary text
        "fg_accent": "#FF00FF",       # Magenta links, highlights
        "fg_sender_me": "#00FF00",    # Bright green my messages
        "fg_sender_other": "#FF4500", # Orange red others' messages
        "fg_mention": "#FFD700",      # Gold mentions background
        "fg_info": "#FFFFFF",         # White info messages
        "fg_timestamp": "#FF6347",    # Tomato timestamps
        "btn_primary": "#DC143C",     # Crimson primary buttons
        "btn_secondary": "#FF1493",   # Hot pink secondary buttons
        "btn_danger": "#FFFF00",      # Yellow danger buttons
        "border": "#FF00FF",          # Magenta borders
        "font_family": "Comic Sans MS",
        "font_size": 16
    }
}

class AnimatedImage:
    def __init__(self, label, data, chat_display):
        self.label = label
        self.chat_display = chat_display
        self.frames = []
        try:
            img = Image.open(io.BytesIO(data))
            for frame in ImageSequence.Iterator(img):
                frame = frame.copy().convert("RGBA")
                frame.thumbnail((400, 400)) # Larger previews
                self.frames.append(ImageTk.PhotoImage(frame))
        except Exception as e:
            print(f"GIF Error: {e}")
            return
        
        self.idx = 0
        if self.frames:
            self.animate()

    def animate(self):
        if not self.label.winfo_exists(): return
        self.label.config(image=self.frames[self.idx])
        self.idx = (self.idx + 1) % len(self.frames)
        self.label.after(80, self.animate)

class ChatClient:
    def __init__(self, server_url: str = ""):
        self.server_url_default = server_url or CHUDSERVE_URL
        self.ws = None
        self.loop = None
        self.root = tk.Tk()
        self.root.title("NAVICHUD")
        self.root.geometry("1100x750") # Slightly larger default
        self.root.configure(bg="#1E1E2E")
        
        # High DPI support
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except: pass
        # Scale for Mac/Linux
        self.root.tk.call('tk', 'scaling', 1.33)

        self.status_var = tk.StringVar(value="Waiting to join...")
        self.remember_var = tk.BooleanVar(value=True)
        self.sync_var = tk.BooleanVar(value=True)
        self.joined = False
        self.username = "Anonymous"
        self.server_url = self.server_url_default
        self.sync_requested = True 
        
        self.images = []
        self.file_refs = {}
        self.file_data_cache = {} # mid (fid) -> bytes
        self.file_data_received = set()
        
        self.current_channel = "General"
        self.channel_history = {cat: [] for cat in CHANNELS} # Stores raw msgs for easy re-display
        self.typing_users = {} # {username: timestamp}
        self.seen_msg_ids = set()
        self.animated_images = [] # Prevent GC
        
        self.is_syncing = False
        self.sync_buffer = []
        self.msg_widgets = {} # {msg_id: (start_index, end_index)}
        self.msg_senders = {} # {msg_id: sender} for rights checking
        self.msg_content_cache = {} # {msg_id: content_text} for reply preview
        
        self.playback_proc = None
        
        # New Feature State
        self.online_users = {} # {username: status}
        self.settings = {"notifications": True, "sound": True}
        self.reply_target = None # msg_id
        self.current_pm_target = None
        self.pm_history = {} # {username: [messages]}
        self.user_statuses = ["Online", "Away", "Busy", "Invisible"]
        self.current_status = "Online"
        self.chud_disabled_var = tk.BooleanVar(value=False)

        # Profile data
        self.user_profile_pics = {} # username: ImageTk.PhotoImage
        self.user_profile_ids = {} # username: file_id
        self.profile_pic_id = None
        self.user_description = ""
        self.user_mood = ""
        self.current_theme = "Dark"  # Default theme

        # Start background connection immediately
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()
        
        self._build_login()

    def _build_login(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.login_frame = tk.Frame(self.root, bg="#1E1E2E")
        self.login_frame.pack(expand=True)

        tk.Label(self.login_frame, text="NAVICHUD",
                 font=("Arial", 28, "bold"), fg="#CDD6F4", bg="#1E1E2E").pack(pady=(30, 12))
        
        tk.Label(self.login_frame, text="Username",
                 font=("Arial", 14), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60)
        self.user_var = tk.StringVar()
        self.user_entry = tk.Entry(self.login_frame, textvariable=self.user_var,
                                   font=("Arial", 14), bg="#313244", fg="#CDD6F4",
                                   insertbackground="white", relief=tk.FLAT)
        self.user_entry.pack(fill=tk.X, padx=60, ipady=10)

        tk.Label(self.login_frame, text="Password",
                 font=("Arial", 14), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(15, 0))
        self.pass_var = tk.StringVar()
        self.pass_entry = tk.Entry(self.login_frame, textvariable=self.pass_var, show="*",
                                   font=("Arial", 14), bg="#313244", fg="#CDD6F4",
                                   insertbackground="white", relief=tk.FLAT)
        self.pass_entry.pack(fill=tk.X, padx=60, ipady=10)

        # Profile Picture Selection
        tk.Label(self.login_frame, text="Profile Picture (optional)",
                 font=("Arial", 14), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(15, 0))
        self.profile_pic_frame = tk.Frame(self.login_frame, bg="#1E1E2E")
        self.profile_pic_frame.pack(fill=tk.X, padx=60, pady=(5, 0))
        self.profile_pic_path = tk.StringVar(value="")
        self.profile_pic_label = tk.Label(self.profile_pic_frame, text="No image selected",
                                          font=("Arial", 12), fg="#A6ADC8", bg="#1E1E2E", anchor="w")
        self.profile_pic_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.select_pic_btn = tkButton(self.profile_pic_frame, text="SELECT IMAGE",
                                       command=self._select_profile_pic,
                                       bg="#313244", fg="#CDD6F4", font=("Arial", 10, "bold"),
                                       relief=tk.FLAT, cursor="hand2", padx=10, pady=5)
        self.select_pic_btn.pack(side=tk.RIGHT)

        self.auth_mode = tk.StringVar(value="login")
        mode_frame = tk.Frame(self.login_frame, bg="#1E1E2E")
        mode_frame.pack(pady=15)
        tk.Radiobutton(mode_frame, text="Login", variable=self.auth_mode, value="login",
                       font=("Arial", 14), bg="#1E1E2E", fg="#A6ADC8", selectcolor="#313244", activebackground="#1E1E2E").pack(side=tk.LEFT, padx=15)
        tk.Radiobutton(mode_frame, text="Register", variable=self.auth_mode, value="register",
                       font=("Arial", 14), bg="#1E1E2E", fg="#A6ADC8", selectcolor="#313244", activebackground="#1E1E2E").pack(side=tk.LEFT, padx=15)

        self.server_frame = tk.Frame(self.login_frame, bg="#1E1E2E")
        tk.Label(self.server_frame, text="Server URL",
                 font=("Arial", 14), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(15, 0))
        self.url_var = tk.StringVar(value=self.server_url_default)
        self.url_entry = tk.Entry(self.server_frame, textvariable=self.url_var,
                 font=("Arial", 13), bg="#313244", fg="#A6ADC8",
                 insertbackground="white", relief=tk.FLAT)
        self.url_entry.pack(fill=tk.X, padx=60, ipady=8)

        tk.Checkbutton(self.login_frame, text="Synchronize History (last 24h)", variable=self.sync_var,
                       font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E", activebackground="#1E1E2E",
                       activeforeground="white", selectcolor="#313244").pack(pady=(15, 0))

        tk.Checkbutton(self.login_frame, text="Remember Me", variable=self.remember_var,
                       font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E", activebackground="#1E1E2E",
                       activeforeground="white", selectcolor="#313244").pack(pady=(5, 15))

        join_btn = tkButton(self.login_frame, text="JOIN CHAT",
                             command=self._start_connect,
                             bg="#89B4FA", fg="#1E1E2E", activebackground="#74C7EC",
                             font=("Arial", 14, "bold"), relief=tk.FLAT, cursor="hand2", padx=40, pady=10)
        join_btn.pack(pady=(15, 0))

        # Custom Server Button
        self.custom_btn = tkButton(self.login_frame, text="SETTINGS / CUSTOM SERVER",
                                    command=self._show_server_settings,
                                    bg="#313244", fg="#CDD6F4", font=("Arial", 10, "bold"),
                                    relief=tk.FLAT, cursor="hand2", activebackground="#45475A")
        self.custom_btn.pack(pady=10)
        self.user_entry.bind("<Return>", lambda _: self._start_connect())

        # Footer Status
        footer = tk.Frame(self.login_frame, bg="#1E1E2E")
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        self.status_label = tk.Label(footer, textvariable=self.status_var, font=("Arial", 11, "italic"),
                                     fg="#89B4FA", bg="#1E1E2E")
        self.status_label.pack()

    def _select_profile_pic(self):
        path = filedialog.askopenfilename(
            title="Select Profile Picture",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff")]
        )
        if path:
            # Validate file size (limit to 5MB for profile pictures)
            if os.path.getsize(path) > 5 * 1024 * 1024:
                messagebox.showerror("File Too Large", "Profile picture must be under 5MB.")
                return
            self.profile_pic_path.set(path)
            filename = os.path.basename(path)
            self.profile_pic_label.config(text=f"Selected: {filename}")
        else:
            self.profile_pic_path.set("")
            self.profile_pic_label.config(text="No image selected")

    def _show_server_settings(self):
        self.server_frame.pack(fill=tk.X, before=self.custom_btn)
        self.custom_btn.pack_forget()

    def _toggle_chud_killswitch(self):
        disabled = self.chud_disabled_var.get()
        if self.ws:
            self._schedule_send({"type": "chud_toggle", "disabled": disabled})
        self._update_user_list_ui()
        self._switch_channel(self.current_channel, force=True)

    def _build_chat_ui(self):
        for widget in self.root.winfo_children():
            widget.pack_forget()

        # Global Footer first (so it stays at bottom)
        footer = tk.Frame(self.root, bg="#11111B", height=28)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = tk.Label(footer, textvariable=self.status_var, font=("Arial", 10, "italic"),
                                     fg="#585B70", bg="#11111B", padx=10)
        self.status_label.pack(side=tk.LEFT)
        
        self.stop_btn = tkButton(footer, text="STOP PLAYBACK", command=self._stop_playback,
                                  font=("Arial", 9, "bold"), bg="#F38BA8", fg="#1E1E2E",
                                  relief=tk.FLAT, padx=10, cursor="hand2")

        # Layout: [Sidebar (Channels)] [Chat Area]
        self.main_pane = tk.Frame(self.root, bg="#1E1E2E")
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sidebar = tk.Frame(self.main_pane, bg="#181825", width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        
        # Header with Settings
        header = tk.Frame(sidebar, bg="#181825")
        header.pack(fill=tk.X, pady=(15, 5))
        tk.Label(header, text="NAVICHUD", font=("Arial", 14, "bold"), fg="#89B4FA", bg="#181825").pack(side=tk.LEFT, padx=15)
        self.profile_label = tk.Label(header, bg="#181825")
        self.profile_label.pack(side=tk.LEFT, padx=5)
        tkButton(header, text="PROFILE", command=self._open_profile, bg="#313244", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 9, "bold"), cursor="hand2").pack(side=tk.RIGHT, padx=10)
        tkButton(header, text="OPTIONS", command=self._open_settings,
                  bg="#313244", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 9, "bold"), cursor="hand2").pack(side=tk.RIGHT, padx=10)

        tk.Label(sidebar, text="CHANNELS", font=("Arial", 10, "bold"), fg="#585B70", bg="#181825", anchor="w").pack(fill=tk.X, padx=15, pady=(10, 5))
        
        self.chan_buttons = {}
        for chan in CHANNELS:
            btn = tkButton(sidebar, text=f"# {chan}", command=lambda c=chan: self._switch_channel(c),
                            bg="#181825", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 12, "bold" if chan=="General" else "normal"),
                            anchor="w", padx=15, pady=5, cursor="hand2", activebackground="#313244")
            btn.pack(fill=tk.X, padx=8)
            self.chan_buttons[chan] = btn

        # Online Users Section
        tk.Label(sidebar, text="USERS ONLINE", font=("Arial", 10, "bold"), fg="#585B70", bg="#181825", anchor="w").pack(fill=tk.X, padx=15, pady=(20, 5))
        self.user_list_frame = tk.Frame(sidebar, bg="#181825")
        self.user_list_frame.pack(fill=tk.X)
        self._update_user_list_ui()

        # PMs Section
        self.pm_label = tk.Label(sidebar, text="PRIVATE MESSAGES", font=("Arial", 10, "bold"), fg="#585B70", bg="#181825", anchor="w")
        self.pm_label.pack(fill=tk.X, padx=15, pady=(20, 5))
        self.pm_list_frame = tk.Frame(sidebar, bg="#181825")
        self.pm_list_frame.pack(fill=tk.X)
        self._update_pm_list_ui()

        self._switch_channel("General", force=True)

        tkButton(sidebar, text="LOG OUT", command=self._logout,
                  font=("Arial", 11, "bold"), bg="#181825", fg="#F38BA8",
                  relief=tk.FLAT, cursor="hand2", padx=15, pady=10).pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=25)

        tk.Checkbutton(sidebar, text="Chud Killswitch", variable=self.chud_disabled_var,
                       command=self._toggle_chud_killswitch,
                       bg="#181825", fg="#F38BA8", activebackground="#181825", activeforeground="#F38BA8",
                       selectcolor="#1E1E2E", font=("Arial", 10, "bold"), cursor="hand2").pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=0)

        # Chat container
        chat_container = tk.Frame(self.main_pane, bg="#1E1E2E")
        chat_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat_display = scrolledtext.ScrolledText(
            chat_container, state="disabled", font=("Arial", 14),
            bg="#181825", fg="#CDD6F4", insertbackground="white",
            relief=tk.FLAT, padx=15, pady=15)
        self.chat_display.pack(padx=12, pady=(12, 0), fill=tk.BOTH, expand=True)
        self.chat_display.tag_config("info", foreground="#585B70", font=("Arial", 12, "italic"))
        self.chat_display.tag_config("timestamp", foreground="#45475A", font=("Arial", 11))
        self.chat_display.tag_config("sender_me", foreground="#89B4FA", font=("Arial", 14, "bold"))
        self.chat_display.tag_config("sender_other", foreground="#A6E3A1", font=("Arial", 14, "bold"))
        self.chat_display.tag_config("mention", background="#FAB387", foreground="#1E1E2E", font=("Arial", 14, "bold"))
        self.chat_display.tag_config("reply", foreground="#585B70", font=("Arial", 12, "italic"))
        self.chat_display.tag_config("file", foreground="#F38BA8")
        # Tags

        # Markdown tags
        self.chat_display.tag_config("bold", font=("Arial", 14, "bold"))
        self.chat_display.tag_config("italic", font=("Arial", 14, "italic"))
        self.chat_display.tag_config("code", font=("Courier New", 13), background="#313244", foreground="#F9E2AF")
        self.chat_display.tag_config("link", foreground="#89B4FA", underline=True)
        self.chat_display.tag_config("channel_link", foreground="#A6E3A1", font=("Arial", 14, "bold"), underline=True)

        # Typing indicator
        self.typing_label = tk.Label(chat_container, text="", font=("Arial", 11, "italic"), fg="#A6ADC8", bg="#1E1E2E", anchor="w")
        self.typing_label.pack(fill=tk.X, padx=20, pady=2)

        # Chat display area... 

        self.emoji_frame = tk.Frame(chat_container, bg="#1E1E2E")
        self.emoji_frame.pack(fill=tk.X, padx=12, pady=(0, 2))
        
        common_emojis = ["👍", "👎", "❤️", "😂", "🔥", "👀", "🤔", "🎉", "💀", "🤓"]
        for emj in common_emojis:
            tkButton(self.emoji_frame, text=emj, font=("Arial", 14), bg="#313244", fg="#CDD6F4", relief=tk.FLAT, cursor="hand2", command=lambda e=emj: self.msg_entry.insert(tk.INSERT, e)).pack(side=tk.LEFT, padx=2)

        input_frame = tk.Frame(chat_container, bg="#313244")
        input_frame.pack(fill=tk.X, padx=12, pady=(2, 15))

        self.msg_entry = tk.Text(input_frame, height=1, undo=True,
                                  font=("Arial", 14), bg="#313244", fg="#CDD6F4",
                                  insertbackground="white", relief=tk.FLAT)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(12, 5))
        
        def _on_enter(event):
            self._send_text()
            return "break"
        self.msg_entry.bind("<Return>", _on_enter)
        self.msg_entry.bind("<Key>", lambda _: self._trigger_typing())
        
        tkButton(input_frame, text="SEND", command=self._send_text,
                  bg="#89B4FA", fg="#1E1E2E", font=("Arial", 12, "bold"),
                  relief=tk.FLAT, cursor="hand2", padx=15).pack(side=tk.LEFT, padx=3, ipady=8)
        
        tkButton(input_frame, text="FILE", command=self._send_file,
                  bg="#313244", fg="#CDD6F4", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2", padx=10).pack(side=tk.LEFT, padx=3, ipady=8)
        
        tkButton(input_frame, text="EMOJI", command=self._show_emoji_picker,
                  bg="#313244", fg="#CDD6F4", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2", padx=10).pack(side=tk.LEFT, padx=3, ipady=8)
        
        # Reply Preview
        self.reply_frame = tk.Frame(chat_container, bg="#11111B")
        self.reply_label = tk.Label(self.reply_frame, text="", bg="#11111B", fg="#A6ADC8", font=("Arial", 11))
        self.reply_label.pack(side=tk.LEFT, padx=10)
        tkButton(self.reply_frame, text="CANCEL REPLY", command=self._cancel_reply, 
                  bg="#11111B", fg="#F38BA8", relief=tk.FLAT, font=("Arial", 10, "bold")).pack(side=tk.RIGHT, padx=5)

        self._check_typing_timeouts()

    def _switch_channel(self, name, force=False):
        if self.current_channel == name and not force: return
        self.current_channel = name
        
        # UI Selection
        all_btns = {**self.chan_buttons}
        if hasattr(self, "user_btns"): all_btns.update(self.user_btns)
        if hasattr(self, "pm_btns"): all_btns.update(self.pm_btns)
        
        for n, btn in all_btns.items():
            if n == name:
                btn.configure(bg="#89B4FA", fg="#1E1E2E")
            else:
                btn.configure(bg="#181825", fg="#CDD6F4")
        
        if hasattr(self, "chat_display") and self.chat_display.winfo_exists():
            try:
                self.chat_display.configure(state="normal")
                self.chat_display.delete("1.0", tk.END)
                
                if name.startswith("@"):
                    self.current_pm_target = name[1:]
                    history = self.pm_history.get(self.current_pm_target, [])
                else:
                    self.current_pm_target = None
                    history = self.channel_history.get(name, [])

                if self.is_syncing and not history and not name.startswith("@"):
                     self.chat_display.insert(tk.END, "\n  ─ LOADING CHAT HISTORY... ─\n", "info")

                for msg in history:
                    self._handle_incoming(msg, is_replay=True)
            finally:
                if self.chat_display.winfo_exists():
                    self.chat_display.configure(state="disabled")
                    self.chat_display.see(tk.END)

    def _update_user_list_ui(self):
        if not hasattr(self, "user_list_frame") or not self.user_list_frame.winfo_exists(): return
        for widget in self.user_list_frame.winfo_children(): widget.destroy()
        self.user_btns = {}
        for user, status in sorted(self.online_users.items()):
            if user == self.username: continue
            if self.chud_disabled_var.get() and user == "Chudbot": continue
            color = "#A6E3A1" if status=="Online" else "#F9E2AF" if status=="Away" else "#F38BA8"
            
            # Create user row frame
            user_row = tk.Frame(self.user_list_frame, bg="#181825")
            user_row.pack(fill=tk.X, pady=2)
            
            # Profile picture (30x30)
            pic_label = tk.Label(user_row, bg="#181825", width=4, height=2)
            pic_label.pack(side=tk.LEFT, padx=(15, 5))
            self._load_profile_pic(user, pic_label)
            
            # Username and status
            btn = tkButton(user_row, text=f"{user} ({status})", command=lambda u=user: self._switch_channel(f"@{u}"),
                            bg="#181825", fg=color, relief=tk.FLAT, font=("Arial", 11),
                            anchor="w", padx=5, pady=2, cursor="hand2")
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # Profile button
            profile_btn = tkButton(user_row, text="👤", command=lambda u=user: self._view_profile(u),
                                 bg="#313244", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 10, "bold"),
                                 cursor="hand2", padx=5, pady=2)
            profile_btn.pack(side=tk.RIGHT, padx=(0, 10))
            
            self.user_btns[f"@{user}"] = btn

    def _load_profile_pic(self, username, label):
        # Load from cache if available
        if username in self.user_profile_pics:
            label.config(image=self.user_profile_pics[username])
            return
        
        # Fallback to initials
        initials = (username[:2].upper() if username else "??")
        label.config(text=initials, font=("Arial", 10, "bold"))

    def _view_profile(self, username):
        """Open a profile view window for the specified user."""
        win = tk.Toplevel(self.root)
        win.title(f"{username}'s Profile")
        win.geometry("400x300")
        win.configure(bg=THEMES[self.current_theme]["bg_primary"])

        # Profile picture
        pic_frame = tk.Frame(win, bg=THEMES[self.current_theme]["bg_primary"])
        pic_frame.pack(pady=20)
        
        pic_label = tk.Label(pic_frame, bg=THEMES[self.current_theme]["bg_primary"], width=10, height=5)
        pic_label.pack()
        
        if username in self.user_profile_pics:
            pic_label.config(image=self.user_profile_pics[username])
        else:
            initials = username[:2].upper() if username else "??"
            pic_label.config(text=initials, font=(THEMES[self.current_theme]["font_family"], 20, "bold"))

        # User info
        info_frame = tk.Frame(win, bg=THEMES[self.current_theme]["bg_primary"])
        info_frame.pack(fill=tk.X, padx=20)

        tk.Label(info_frame, text=f"Username: {username}", font=(THEMES[self.current_theme]["font_family"], 14), 
                 bg=THEMES[self.current_theme]["bg_primary"], fg=THEMES[self.current_theme]["fg_primary"]).pack(anchor="w")
        
        status = self.online_users.get(username, "Unknown")
        tk.Label(info_frame, text=f"Status: {status}", font=(THEMES[self.current_theme]["font_family"], 14), 
                 bg=THEMES[self.current_theme]["bg_primary"], fg=THEMES[self.current_theme]["fg_primary"]).pack(anchor="w", pady=(5, 0))

        # Get user description and mood from server
        self._schedule_send({"type": "get_profile", "username": username})
        
        # Close button
        tkButton(win, text="Close", command=win.destroy, bg=THEMES[self.current_theme]["btn_primary"], 
                 fg=THEMES[self.current_theme]["bg_primary"], font=(THEMES[self.current_theme]["font_family"], 12, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=10).pack(pady=20)

    def _update_pm_list_ui(self):
        if not hasattr(self, "pm_list_frame") or not self.pm_list_frame.winfo_exists(): return
        for widget in self.pm_list_frame.winfo_children(): widget.destroy()
        self.pm_btns = {}
        for user in sorted(self.pm_history.keys()):
            btn = tkButton(self.pm_list_frame, text=f"{user}", command=lambda u=user: self._switch_channel(f"@{u}"),
                             bg="#181825", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 11),
                             anchor="w", padx=15, pady=2, cursor="hand2")
            btn.pack(fill=tk.X)
            self.pm_btns[f"@{user}"] = btn

    def _trigger_typing(self):
        self._schedule_send({"type": "typing", "sender": self.username, "channel": self.current_channel})

    def _check_typing_timeouts(self):
        if not hasattr(self, "typing_label") or not self.typing_label.winfo_exists(): return
        now = time.time()
        to_del = [u for u, ts in self.typing_users.items() if now - ts > 3]
        for u in to_del: del self.typing_users[u]
        
        if self.typing_users:
            users = list(self.typing_users.keys())
            if len(users) == 1: text = f"{users[0]} is typing..."
            else: text = f"{', '.join(users[:-1])} and {users[-1]} are typing..."
            self.typing_label.config(text=text)
        else:
            self.typing_label.config(text="")
        self.root.after(1000, self._check_typing_timeouts)

    def _delegate_scroll(self, event):
        if hasattr(self, "chat_display") and self.chat_display.winfo_exists():
            if event.num == 5 or event.delta < 0:
                self.chat_display.yview_scroll(1, "units")
            elif event.num == 4 or event.delta > 0:
                self.chat_display.yview_scroll(-1, "units")

    def _append(self, sender, content, tag="", is_me=False, image=None, timestamp=None, mid=None, reply_to=None):
        if not hasattr(self, "chat_display") or not self.chat_display.winfo_exists(): return
        
        try:
            self.chat_display.configure(state="normal")
            start_idx = self.chat_display.index(tk.INSERT)
            
            # Reply Context
            if reply_to:
                # Resolve the reply_to ID to actual message text
                replied_sender = self.msg_senders.get(reply_to, "")
                replied_text = self.msg_content_cache.get(reply_to, "")
                if replied_text:
                    preview = (replied_text[:45] + "...") if len(replied_text) > 45 else replied_text
                    reply_line = f"  [ {replied_sender}: {preview} ]\n" if replied_sender else f"  [ {preview} ]\n"
                else:
                    reply_line = f"  [ Replying to message ]\n"
                self.chat_display.insert(tk.END, reply_line, "reply")

            ts_str = ""
            if timestamp:
                dt = datetime.fromtimestamp(timestamp)
                ts_str = dt.strftime("[%H:%M] ")
            
            if tag == "info":
                self.chat_display.insert(tk.END, f"\n  ─ {content} ─\n", "info")
            else:
                if ts_str: self.chat_display.insert(tk.END, ts_str, "timestamp")

                if sender in self.user_profile_pics:
                    pic_label = tk.Label(self.chat_display, image=self.user_profile_pics[sender], bg="#181825")
                    pic_label.bind("<MouseWheel>", self._delegate_scroll)
                    self.chat_display.window_create(tk.END, window=pic_label)
                    self.chat_display.insert(tk.END, " ")

                display_name = "Me" if is_me else sender
                name_tag = "sender_me" if is_me else "sender_other"

                self.chat_display.insert(tk.END, f"{display_name}: ", name_tag)
                
                # Mention Check
                is_mention = f"@{self.username}" in content
                current_tag = "mention" if is_mention else (tag or "")

                if image:
                    img_lbl = tk.Label(self.chat_display, image=image, bg="#181825")
                    img_lbl.bind("<MouseWheel>", self._delegate_scroll)
                    img_lbl.bind("<Button-4>", self._delegate_scroll)
                    img_lbl.bind("<Button-5>", self._delegate_scroll)
                    
                    for b in ["<Button-2>", "<Button-3>", "<Control-Button-1>"]:
                        img_lbl.bind(b, lambda e, m=mid: self._show_context_menu(e, m))
                    
                    self.chat_display.window_create(tk.END, window=img_lbl)
                    self.chat_display.insert(tk.END, "\n")
                else:
                    self._insert_markdown(content, current_tag)
                    self.chat_display.insert(tk.END, "\n")
                    
                    if mid:
                        msg_tag = f"msg_{mid}"
                        self.chat_display.tag_add(msg_tag, start_idx, self.chat_display.index(tk.INSERT))
                        for b in ["<Button-2>", "<Button-3>", "<Control-Button-1>"]:
                            self.chat_display.tag_bind(msg_tag, b, lambda e, m=mid: self._show_context_menu(e, m))
                
            if mid:
                end_idx = self.chat_display.index(tk.INSERT)
                self.msg_widgets[mid] = (start_idx, end_idx)
                self.msg_senders[mid] = sender
                if content:
                    self.msg_content_cache[mid] = content

        finally:
            if self.chat_display.winfo_exists():
                self.chat_display.configure(state="disabled")
                self.chat_display.see(tk.END)

    def _insert_markdown(self, content, base_tag=""):
        # Pattern for Bold, Italic, Code, Hyperlinks, and #Channels
        pattern = re.compile(r'(\*\*.+?\*\*|\*.+?[\*]|`.+?`|https?://\S+|#\w+)')
        remaining = content
        while remaining:
            match = pattern.search(remaining)
            if not match:
                self.chat_display.insert(tk.END, remaining, base_tag)
                break
            
            # Text before match
            self.chat_display.insert(tk.END, remaining[:match.start()], base_tag)
            m = match.group(0)
            
            if m.startswith("**") and m.endswith("**"):
                self.chat_display.insert(tk.END, m[2:-2], ("bold", base_tag))
            elif m.startswith("*") and m.endswith("*"):
                self.chat_display.insert(tk.END, m[1:-1], ("italic", base_tag))
            elif m.startswith("`") and m.endswith("`"):
                self.chat_display.insert(tk.END, m[1:-1], ("code", base_tag))
            elif m.startswith("http"):
                self.chat_display.insert(tk.END, m, ("link", base_tag))
                # Make link clickable
                start_idx = self.chat_display.index(f"{tk.INSERT} - {len(m)}c")
                end_idx = self.chat_display.index(tk.INSERT)
                self.chat_display.tag_add("clickable_link", start_idx, end_idx)
                self.chat_display.tag_bind("clickable_link", "<Button-1>", lambda e, url=m: self._open_url(url))
                self.chat_display.tag_config("clickable_link", foreground="#89B4FA", underline=True)
            elif m.startswith("#"):
                chan_name = m[1:]
                if chan_name in CHANNELS:
                     self.chat_display.insert(tk.END, m, ("channel_link", base_tag))
                     start_idx = self.chat_display.index(f"{tk.INSERT} - {len(m)}c")
                     end_idx = self.chat_display.index(tk.INSERT)
                     tag_name = f"chan_{chan_name}_{uuid.uuid4().hex[:4]}"
                     self.chat_display.tag_add(tag_name, start_idx, end_idx)
                     self.chat_display.tag_bind(tag_name, "<Button-1>", lambda e, c=chan_name: self._switch_channel(c))
                     self.chat_display.tag_config(tag_name, foreground="#A6E3A1", font=("Arial", 14, "bold"), underline=True)
                else:
                     self.chat_display.insert(tk.END, m, base_tag)
            else:
                self.chat_display.insert(tk.END, m, base_tag)
            
            remaining = remaining[match.end():]

    def _open_url(self, url):
        if sys.platform == "darwin": subprocess.run(["open", url])
        elif sys.platform == "win32": os.startfile(url)
        else: subprocess.run(["xdg-open", url])

    def _show_context_menu(self, event, mid):
        menu = tk.Menu(self.root, tearoff=0, bg="#313244", fg="white", activebackground="#89B4FA")
        
        is_file = mid in self.file_refs
        sender = self.msg_senders.get(mid)
        is_me = (sender == self.username)
        
        # Add React Submenu
        react_menu = tk.Menu(menu, tearoff=0, bg="#313244", fg="white", activebackground="#89B4FA")
        for emj in ["👍", "👎", "❤️", "😂", "🔥", "👀", "🤔", "🎉", "💀", "🤓"]:
            react_menu.add_command(label=emj, command=lambda m=mid, e=emj: self._react_to_msg(m, e))
        menu.add_cascade(label="Add Reaction...", menu=react_menu)
        menu.add_separator()
        
        menu.add_command(label="Reply", command=lambda m=mid: self._set_reply(m))
        if not is_me:
            menu.add_command(label=f"Message @{sender}", command=lambda u=sender: self._switch_channel(f"@{u}"))

        if is_file:
            data = self.file_data_cache.get(mid)
            if data:
                ref = self.file_refs[mid]
                menu.add_command(label="Save File", command=lambda: self._save_file(ref['filename'], data))
        
        if is_me:
            menu.add_separator()
            if not is_file:
                menu.add_command(label="Edit Message", command=lambda m=mid: self._request_edit(m))
            menu.add_command(label="Delete", command=lambda m=mid: self._request_delete(m), foreground="#F38BA8")
        
        menu.tk_popup(event.x_root, event.y_root)

    def _react_to_msg(self, mid, emoji):
        self._set_reply(mid)
        self._send_emoji(emoji)

    def _set_reply(self, mid):
        self.reply_target = mid
        sender = self.msg_senders.get(mid, "")
        text = self.msg_content_cache.get(mid, "")
        if text:
            preview = (text[:40] + "...") if len(text) > 40 else text
            label = f"Replying to {sender}: {preview}" if sender else f"Replying to: {preview}"
        else:
            label = "Replying to message"
        self.reply_label.config(text=label)
        self.reply_frame.pack(side=tk.BOTTOM, fill=tk.X, before=self.msg_entry.master)

    def _cancel_reply(self):
        self.reply_target = None
        self.reply_frame.pack_forget()

    def _request_delete(self, mid):
        self._schedule_send({"type": "delete", "msg_id": mid})

    def _request_edit(self, mid):
        # Find current text
        history = []
        for c in self.channel_history.values(): history.extend(c)
        current_text = ""
        for m in history:
            if m.get("msg_id") == mid:
                current_text = m.get("content", "")
                break
        
        new_text = simpledialog.askstring("Edit Message", "Update your message:", initialvalue=current_text)
        if new_text is not None and new_text != current_text:
            self._schedule_send({"type": "edit", "msg_id": mid, "content": new_text})

    def _save_file(self, filename, data, open_after=False):
        try:
            if open_after:
                # Play/open without saving to Downloads - use temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
                    tmp.write(data)
                    save_path = tmp.name

                is_video = any(filename.lower().endswith(e) for e in [".mp4", ".mov", ".avi", ".mkv"])
                is_audio = any(filename.lower().endswith(e) for e in [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aiff"])

                if is_audio and sys.platform == "darwin":
                    try:
                        self._stop_playback()
                        self.playback_proc = subprocess.Popen(["afplay", save_path])
                        self._setStatus(f"Playing: {filename}", "#A6E3A1")
                        if hasattr(self, "stop_btn"): self.stop_btn.pack(side=tk.RIGHT, padx=5)
                    except Exception as e:
                        print(f"afplay failed: {e}")
                elif is_video or is_audio:
                    # Use OS default (QuickTime for video on Mac)
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", save_path])
                    elif sys.platform == "win32":
                        os.startfile(save_path)
                    else:
                        subprocess.Popen(["xdg-open", save_path])
                else:
                    if sys.platform == "darwin": subprocess.run(["open", save_path])
                    elif sys.platform == "win32": os.startfile(save_path)
                    else: subprocess.run(["xdg-open", save_path])
                return

            # Manual save to downloads
            downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(downloads_path, exist_ok=True)
            save_path = os.path.join(downloads_path, filename)
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(save_path):
                save_path = os.path.join(downloads_path, f"{base}_{counter}{ext}")
                counter += 1
            with open(save_path, "wb") as f: f.write(data)
            messagebox.showinfo("File Saved", f"Saved to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _stop_playback(self):
        if self.playback_proc:
            try: self.playback_proc.terminate()
            except: pass
            self.playback_proc = None
        if hasattr(self, "stop_btn") and self.stop_btn.winfo_exists():
            self.stop_btn.pack_forget()
        self._setStatus("Connected", "#585B70")

    def _show_emoji_picker(self):
        if sys.platform == "darwin":
            # Direct keystroke combo often fails without accessibility permissions, 
            # so we use characters palette name
            subprocess.run(["osascript", "-e", 'tell application "System Events" to set visible of process "ControlCenter" to false',
                             "-e", 'tell application "System Events" to keystroke (ASCII character 32) using {control down, command down}'])
        elif sys.platform == "win32":
            subprocess.run(["powershell", "-c", "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('^{ESC}')"])
        else:
            subprocess.run(["ibus", "emoji"])

    def _play_sound(self, sound="Glass"):
        if not self.settings.get("sound"): return
        path = f"/System/Library/Sounds/{sound}.aiff"
        if os.path.exists(path):
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _setStatus(self, text, color="#89B4FA"):
        self.status_var.set(text)
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.configure(fg=color)

    def _apply_theme(self):
        """Apply the current theme to all UI elements."""
        if self.current_theme not in THEMES:
            return

        theme = THEMES[self.current_theme]

        # Apply to root window
        self.root.configure(bg=theme["bg_primary"])

        # Apply to login frame if it exists
        if hasattr(self, "login_frame") and self.login_frame.winfo_exists():
            self.login_frame.configure(bg=theme["bg_primary"])
            # Update all login widgets
            for widget in self.login_frame.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.configure(bg=theme["bg_primary"], fg=theme["fg_primary"])
                elif isinstance(widget, tk.Entry):
                    widget.configure(bg=theme["bg_accent"], fg=theme["fg_primary"], insertbackground=theme["fg_primary"])
                elif isinstance(widget, tk.Button):
                    widget.configure(bg=theme["btn_primary"], fg=theme["bg_primary"])
                elif isinstance(widget, tk.Radiobutton):
                    widget.configure(bg=theme["bg_primary"], fg=theme["fg_secondary"], selectcolor=theme["bg_accent"])
                elif isinstance(widget, tk.Checkbutton):
                    widget.configure(bg=theme["bg_primary"], fg=theme["fg_secondary"], selectcolor=theme["bg_accent"])
                elif isinstance(widget, tk.Frame):
                    widget.configure(bg=theme["bg_primary"])

        # Apply to main chat UI
        if hasattr(self, "main_pane") and self.main_pane.winfo_exists():
            self.main_pane.configure(bg=theme["bg_primary"])

            # Sidebar
            sidebar = self.main_pane.winfo_children()[0] if self.main_pane.winfo_children() else None
            if sidebar:
                sidebar.configure(bg=theme["bg_secondary"])
                for widget in sidebar.winfo_children():
                    if isinstance(widget, tk.Label):
                        widget.configure(bg=theme["bg_secondary"], fg=theme["fg_secondary"])
                    elif isinstance(widget, tk.Frame):
                        widget.configure(bg=theme["bg_secondary"])
                        # Update buttons in frames
                        for btn in widget.winfo_children():
                            if isinstance(btn, tkButton):
                                if btn.cget("bg") == "#89B4FA":  # Selected channel
                                    btn.configure(bg=theme["btn_primary"], fg=theme["bg_primary"])
                                else:
                                    btn.configure(bg=theme["bg_secondary"], fg=theme["fg_primary"])
                    elif isinstance(widget, tkButton):
                        if widget.cget("bg") == "#89B4FA":  # Selected channel
                            widget.configure(bg=theme["btn_primary"], fg=theme["bg_primary"])
                        else:
                            widget.configure(bg=theme["bg_secondary"], fg=theme["fg_primary"])

            # Chat container
            chat_container = self.main_pane.winfo_children()[1] if len(self.main_pane.winfo_children()) > 1 else None
            if chat_container:
                chat_container.configure(bg=theme["bg_primary"])

                # Chat display
                if hasattr(self, "chat_display") and self.chat_display.winfo_exists():
                    self.chat_display.configure(
                        bg=theme["bg_secondary"],
                        fg=theme["fg_primary"],
                        insertbackground=theme["fg_primary"]
                    )
                    # Update tag colors
                    self.chat_display.tag_config("info", foreground=theme["fg_info"])
                    self.chat_display.tag_config("timestamp", foreground=theme["fg_timestamp"])
                    self.chat_display.tag_config("sender_me", foreground=theme["fg_sender_me"])
                    self.chat_display.tag_config("sender_other", foreground=theme["fg_sender_other"])
                    self.chat_display.tag_config("mention", background=theme["fg_mention"], foreground=theme["bg_primary"])
                    self.chat_display.tag_config("reply", foreground=theme["fg_info"])
                    self.chat_display.tag_config("code", background=theme["bg_accent"], foreground=theme["fg_accent"])
                    self.chat_display.tag_config("link", foreground=theme["fg_accent"])
                    self.chat_display.tag_config("channel_link", foreground=theme["fg_sender_other"])

                # Emoji frame
                if hasattr(self, "emoji_frame") and self.emoji_frame.winfo_exists():
                    self.emoji_frame.configure(bg=theme["bg_primary"])
                    for btn in self.emoji_frame.winfo_children():
                        if isinstance(btn, tkButton):
                            btn.configure(bg=theme["bg_accent"], fg=theme["fg_primary"])

                # Input frame
                input_frame = chat_container.winfo_children()[2] if len(chat_container.winfo_children()) > 2 else None
                if input_frame:
                    input_frame.configure(bg=theme["bg_accent"])
                    for widget in input_frame.winfo_children():
                        if isinstance(widget, tk.Text):
                            widget.configure(bg=theme["bg_accent"], fg=theme["fg_primary"], insertbackground=theme["fg_primary"])
                        elif isinstance(btn, tkButton):
                            btn.configure(bg=theme["btn_primary"], fg=theme["bg_primary"])

                # Typing label
                if hasattr(self, "typing_label") and self.typing_label.winfo_exists():
                    self.typing_label.configure(bg=theme["bg_primary"], fg=theme["fg_secondary"])

                # Reply frame
                if hasattr(self, "reply_frame") and self.reply_frame.winfo_exists():
                    self.reply_frame.configure(bg=theme["bg_tertiary"])
                    for widget in self.reply_frame.winfo_children():
                        if isinstance(widget, tk.Label):
                            widget.configure(bg=theme["bg_tertiary"], fg=theme["fg_secondary"])
                        elif isinstance(widget, tkButton):
                            widget.configure(bg=theme["bg_tertiary"], fg=theme["btn_danger"])

        # Footer
        footer = self.root.winfo_children()[-1] if self.root.winfo_children() else None
        if footer and isinstance(footer, tk.Frame):
            footer.configure(bg=theme["bg_tertiary"])
            for widget in footer.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.configure(bg=theme["bg_tertiary"], fg=theme["fg_info"])
                elif isinstance(widget, tkButton):
                    widget.configure(bg=theme["btn_danger"], fg=theme["bg_primary"])

        # Update fonts throughout the UI
        font_family = theme["font_family"]
        font_size = theme["font_size"]

        def update_fonts(widget):
            try:
                current_font = widget.cget("font")
                if isinstance(current_font, str):
                    # Parse font string like "Arial 14 bold"
                    parts = current_font.split()
                    if len(parts) >= 2:
                        new_font = (font_family, font_size, *parts[2:])
                        widget.configure(font=new_font)
                elif isinstance(current_font, tuple):
                    new_font = (font_family, font_size, *current_font[2:])
                    widget.configure(font=new_font)
            except:
                pass

        # Apply font updates to key widgets
        if hasattr(self, "chat_display") and self.chat_display.winfo_exists():
            update_fonts(self.chat_display)

    def _open_profile(self):
        win = tk.Toplevel(self.root)
        win.title("Profile")
        win.geometry("400x350")
        win.configure(bg=THEMES[self.current_theme]["bg_primary"])

        tk.Label(win, text="Description", font=(THEMES[self.current_theme]["font_family"], 14), bg=THEMES[self.current_theme]["bg_primary"], fg=THEMES[self.current_theme]["fg_primary"]).pack(pady=(20, 5))

        desc_var = tk.StringVar(value=self.user_description)
        desc_entry = tk.Entry(win, textvariable=desc_var, font=(THEMES[self.current_theme]["font_family"], 14), bg=THEMES[self.current_theme]["bg_accent"], fg=THEMES[self.current_theme]["fg_primary"], insertbackground=THEMES[self.current_theme]["fg_primary"], relief=tk.FLAT)
        desc_entry.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(win, text="Mood Emoji", font=(THEMES[self.current_theme]["font_family"], 14), bg=THEMES[self.current_theme]["bg_primary"], fg=THEMES[self.current_theme]["fg_primary"]).pack(pady=(10, 5))

        mood_var = tk.StringVar(value=self.user_mood)
        mood_entry = tk.Entry(win, textvariable=mood_var, font=(THEMES[self.current_theme]["font_family"], 14), bg=THEMES[self.current_theme]["bg_accent"], fg=THEMES[self.current_theme]["fg_primary"], insertbackground=THEMES[self.current_theme]["fg_primary"], relief=tk.FLAT)
        mood_entry.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(win, text="Theme", font=(THEMES[self.current_theme]["font_family"], 14), bg=THEMES[self.current_theme]["bg_primary"], fg=THEMES[self.current_theme]["fg_primary"]).pack(pady=(10, 5))

        theme_var = tk.StringVar(value=self.current_theme)
        theme_menu = tk.OptionMenu(win, theme_var, *THEMES.keys())
        theme_menu.config(bg=THEMES[self.current_theme]["bg_accent"], fg=THEMES[self.current_theme]["fg_primary"], relief=tk.FLAT, font=(THEMES[self.current_theme]["font_family"], 12), highlightthickness=0)
        theme_menu.pack(pady=(0, 20))

        def save():
            desc = desc_var.get()
            mood = mood_var.get()
            theme = theme_var.get()
            self._schedule_send({"type": "update_profile", "description": desc, "mood_emoji": mood, "theme": theme})
            self.user_description = desc
            self.user_mood = mood
            if theme != self.current_theme:
                self.current_theme = theme
                self._apply_theme()
            win.destroy()

        tkButton(win, text="SAVE", command=save, bg=THEMES[self.current_theme]["btn_primary"], fg=THEMES[self.current_theme]["bg_primary"], font=(THEMES[self.current_theme]["font_family"], 12, "bold"), relief=tk.FLAT, cursor="hand2", padx=20, pady=10).pack()

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("NAVICHUD SETTINGS")
        win.geometry("400x450")
        win.configure(bg="#1E1E2E")
        
        tk.Label(win, text="Settings", font=("Arial", 18, "bold"), bg="#1E1E2E", fg="#CDD6F4").pack(pady=20)
        
        # Audio/Notifications
        for key, label in [("sound", "Sound Effects"), ("notifications", "Show Notifications")]:
            var = tk.BooleanVar(value=self.settings.get(key, True))
            def update(k=key, v=var): self.settings[k] = v.get()
            tk.Checkbutton(win, text=label, variable=var, command=update,
                           font=("Arial", 14), bg="#1E1E2E", fg="#A6ADC8", selectcolor="#313244", activebackground="#1E1E2E").pack(pady=10, anchor="w", padx=50)
        
        # Status
        tk.Label(win, text="My Status", font=("Arial", 14), bg="#1E1E2E", fg="#CDD6F4").pack(pady=(20, 5))
        status_var = tk.StringVar(value=self.current_status)
        def change_status(val):
            self.current_status = val
            self._schedule_send({"type": "status_update", "sender": self.username, "status": val})
        
        opt = tk.OptionMenu(win, status_var, *self.user_statuses, command=change_status)
        opt.config(bg="#313244", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 12))
        opt.pack(pady=10)

    def _logout(self):
        self.joined = False
        self.username = "Anonymous"
        if os.path.exists(SESSION_FILE):
            try: os.remove(SESSION_FILE)
            except: pass
        if self.ws:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
        self._setStatus("Logged out.", "#A6ADC8")
        self._build_login()

    def _start_connect(self):
        user = self.user_var.get().strip()
        pwd  = self.pass_var.get().strip()
        url  = self.url_var.get().strip() or self.server_url
        if not user: return

        hashed_pwd = hashlib.sha256(pwd.encode()).hexdigest()
        mode = self.auth_mode.get()

        # Prepare profile picture data if selected
        profile_pic_data = None
        profile_pic_filename = None
        if self.profile_pic_path.get():
            try:
                with open(self.profile_pic_path.get(), "rb") as f:
                    profile_pic_data = base64.b64encode(f.read()).decode("ascii")
                profile_pic_filename = os.path.basename(self.profile_pic_path.get())
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read profile picture: {e}")
                return

        if url != self.server_url:
            # Different server — update and force reconnect
            self.server_url = url
            self.username = user
            if self.ws:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
        else:
            # Same server — send auth directly on open connection
            payload = {
                "type": mode,
                "sender": user,
                "password": hashed_pwd,
                "sync": self.sync_var.get(),
                "remember": self.remember_var.get()
            }
            if profile_pic_data and mode == "register":
                payload["profile_pic_data"] = profile_pic_data
                payload["profile_pic_filename"] = profile_pic_filename
            self._schedule_send(payload)

    def _flush_sync_buffer(self):
        if not hasattr(self, "chat_display"): return
        # Create a copy and clear to avoid recursion if _handle_incoming buffers again
        buffer = self.sync_buffer[:]
        self.sync_buffer = []
        for m in buffer:
            self._handle_incoming(m, is_replay=True)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        while True: # Auto Reconnect
            try:
                self.loop.run_until_complete(self._connect())
            except Exception as e:
                err_msg = f"Connection lost. Retrying in 5s... ({e})"
                print(err_msg)
                self._setStatus(err_msg, "#F38BA8")
                time.sleep(5)

    async def _connect(self):
        self._setStatus(f"Connecting to {self.server_url}...", "#89B4FA")
        try:
            async with websockets.connect(self.server_url, max_size=104857600,
                                          ping_interval=30, ping_timeout=60) as ws:
                self.ws = ws
                
                # Session token auto-login
                if os.path.exists(SESSION_FILE):
                    try:
                        with open(SESSION_FILE, "r") as f:
                            token = f.read().strip()
                        if token:
                            self._setStatus("Restoring session...", "#A6ADC8")
                            await ws.send(json.dumps({
                                "type": "token_login",
                                "token": token,
                                "sync": True,
                                "remember": True
                            }))
                            await self._receive_loop(ws)
                            return  # handled entirely by receive_loop
                    except Exception as e:
                        print(f"Token login error: {e}")
                        try: os.remove(SESSION_FILE)
                        except: pass

                # No session file or token login failed — wait for user to hit JOIN in the UI
                self._setStatus("Connected. Please log in.", "#585B70")
                await self._receive_loop(ws)
        except Exception as e:
            raise  # Let _run_loop handle reconnect

    async def _receive_loop(self, ws):
        async for raw in ws:
            msg = json.loads(raw)
            self.root.after(0, self._handle_incoming, msg)

    def _handle_incoming(self, msg, is_replay=False):
        t = msg.get("type", "text")
        
        if t == "user_list":
            users_dict = msg.get("users", {})
            self.online_users = {u: info.get("status", "Online") for u, info in users_dict.items()}
            self.user_profile_ids = {u: info.get("profile_pic") for u, info in users_dict.items() if info.get("profile_pic")}
            for u, fid in self.user_profile_ids.items():
                if fid and u not in self.user_profile_pics:
                    self._schedule_send({"type": "file_request", "file_id": fid})
            self._update_user_list_ui()  # guarded inside with hasattr check
            count = len(self.online_users)
            if self.joined:
                self._setStatus(f"Logged in as {self.username} ({count} Online)", "#A6E3A1")
            return

        if t == "pm":
            sender = msg.get("sender")
            content = msg.get("content")
            other = sender if sender != self.username else msg.get("target")
            
            if other not in self.pm_history:
                self.pm_history[other] = []
                self._update_pm_list_ui()
            
            if not any(m.get("msg_id") == msg.get("msg_id") for m in self.pm_history[other]):
                self.pm_history[other].append(msg)
            
            if not is_replay and sender != self.username:
                self._play_sound("Ping")
            
            if self.current_channel == f"@{other}":
                self._append(sender, content, is_me=(sender == self.username), mid=msg.get("msg_id"), timestamp=msg.get("timestamp"), reply_to=msg.get("reply_to"))
            return

        if t == "sync_finished":
            self.is_syncing = False
            count = len(self.online_users)
            self._setStatus(f"Logged in as {self.username} ({count} Online)", "#A6E3A1")
            if self.joined and hasattr(self, "chat_display"):
                self._switch_channel(self.current_channel, force=True)
            return
        
        if t == "auth_success":
            user = msg.get("username", "Anonymous")
            token = msg.get("token")
            if token:
                try:
                    with open(SESSION_FILE, "w") as f: f.write(token)
                except: pass

            self._setStatus(f"Logged in as {user}", "#A6E3A1")
            if user != "Anonymous":
                self.username = user
                self.profile_pic_id = msg.get("profile_pic")
                self.user_description = msg.get("description", "")
                self.user_mood = msg.get("mood_emoji", "")
                user_theme = msg.get("theme", "Dark")
                if user_theme in THEMES and user_theme != self.current_theme:
                    self.current_theme = user_theme
                if self.profile_pic_id:
                    self._schedule_send({"type": "file_request", "file_id": self.profile_pic_id})
                already_joined = self.joined
                self.joined = True
                if not already_joined:
                    self.is_syncing = True  # history is incoming after auth
                    self._build_chat_ui()
                    # Defer flush until sync_finished arrives
            return
        
        if t == "auth_error":
            # If session was rejected, clean up
            if os.path.exists(SESSION_FILE):
                try: os.remove(SESSION_FILE)
                except: pass
            self._setStatus(msg.get("content", "Error"), "#F38BA8")
            self.joined = False
            self._build_login() 
            return

        if t == "delete_notify":
            mid = msg.get("msg_id")
            if mid in self.msg_widgets:
                if hasattr(self, "chat_display") and self.chat_display.winfo_exists():
                    start, end = self.msg_widgets[mid]
                    try:
                        self.chat_display.configure(state="normal")
                        self.chat_display.delete(start, end)
                        self.chat_display.insert(start, " (( message deleted )) \n", "info")
                    finally:
                        self.chat_display.configure(state="disabled")
            
            # Update local history
            for cname in self.channel_history:
                self.channel_history[cname] = [m for m in self.channel_history[cname] if (m.get("msg_id") or m.get("file_id")) != mid]
            return

        if t == "edit_notify":
            mid = msg.get("msg_id")
            new_val = msg.get("content")
            if mid in self.msg_widgets and hasattr(self, "chat_display") and self.chat_display.winfo_exists():
                start, end = self.msg_widgets[mid]
                sender = self.msg_senders.get(mid, "?")
                is_me = (sender == self.username)
                try:
                    self.chat_display.configure(state="normal")
                    self.chat_display.delete(start, end)
                    # Re-insert with markdown
                    self.chat_display.mark_set("insert", start)
                    
                    # Redo the prefix (timestamp + name)
                    # To keep it simple, we use a slightly simplified re-insert for edits
                    display_name = "Me" if is_me else sender
                    name_tag = "sender_me" if is_me else "sender_other"
                    self.chat_display.insert(start, f"{display_name}: ", name_tag)
                    self._insert_markdown(new_val)
                    self.chat_display.insert(tk.INSERT, " (edited)\n", "info")
                    
                    # Update widget mapping end point
                    new_end = self.chat_display.index(tk.INSERT)
                    self.msg_widgets[mid] = (start, new_end)
                    
                    # Re-bind tag if it was text
                    msg_tag = f"msg_{mid}"
                    self.chat_display.tag_add(msg_tag, start, new_end)
                    for b in ["<Button-2>", "<Button-3>", "<Control-Button-1>"]:
                        self.chat_display.tag_bind(msg_tag, b, lambda e, m=mid: self._show_context_menu(e, m))
                finally:
                    self.chat_display.configure(state="disabled")
            
            # Update local history
            for cname in self.channel_history:
                for m in self.channel_history[cname]:
                    if m.get("msg_id") == mid: m["content"] = new_val
            return

        sender = msg.get("sender", "?")
        channel = msg.get("channel", "General")
        is_me = (sender == self.username)
        ts = msg.get("timestamp", time.time())
        mid = msg.get("msg_id") or msg.get("file_id")

        if t == "typing":
            if channel == self.current_channel and sender != self.username:
                self.typing_users[sender] = time.time()
            return

        # Cache & Deduplicate (ALWAYS do this so channel history works)
        if mid:
            if mid in self.seen_msg_ids and not is_replay:
                return
            self.seen_msg_ids.add(mid)

        if channel in self.channel_history and not is_replay:
            # Avoid dupes in channel cache for messages with IDs
            if mid:
                if not any((m.get("msg_id") or m.get("file_id")) == mid for m in self.channel_history[channel]):
                    self.channel_history[channel].append(msg)
            else:
                # System messages/info typically have no ID, so just append
                self.channel_history[channel].append(msg)

        if not self.joined and not is_replay:
            self.sync_buffer.append(msg)
            return

        if channel == self.current_channel and sender in self.typing_users:
            del self.typing_users[sender]

        if channel != self.current_channel and t != "info": return

        # Chud Killswitch hiding
        if self.chud_disabled_var.get() and sender == "Chudbot" and t in ("text", "emoji", "pm", "file_ref", "file_data"):
            return

        if t == "text":
            if not is_replay and f"@{self.username}" in msg.get("content", ""):
                 self._play_sound("Basso") # Special mention sound
            self._append(sender, msg.get("content", ""), mid=mid, is_me=is_me, timestamp=ts, reply_to=msg.get("reply_to"))
        elif t == "emoji":
            self._append(sender, msg.get("content", ""), mid=mid, is_me=is_me, timestamp=ts, reply_to=msg.get("reply_to"))
        elif t == "info":
            self._append(sender, msg.get("content", ""), "info", timestamp=ts)
        elif t == "file_ref":
            fid = msg.get("file_id", "")
            self.file_refs[fid] = msg
            if fid not in self.file_data_received:
                self._schedule_send({"type": "file_request", "file_id": fid})
        elif t == "file_data":
            fid = msg.get("file_id", "")
            self.file_data_received.add(fid)
            ref = self.file_refs.get(fid, {})
            mime = msg.get("mime", ref.get("mime", ""))
            filename = msg.get("filename", ref.get("filename", "file"))
            data = base64.b64decode(msg.get("data", ""))
            self.file_data_cache[fid] = data # Cache for right-click save

            # Check if it's a profile pic
            if fid in self.user_profile_ids.values() or fid == self.profile_pic_id:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((32, 32))
                    tk_img = ImageTk.PhotoImage(img)
                    username = None
                    if fid == self.profile_pic_id:
                        username = self.username
                    else:
                        for u, id in self.user_profile_ids.items():
                            if id == fid:
                                username = u
                                break
                    if username:
                        self.user_profile_pics[username] = tk_img
                        if username == self.username and hasattr(self, "profile_label"):
                            self.profile_label.config(image=tk_img)
                except Exception as e:
                    print(f"Profile pic error: {e}")

            if mime.startswith("image/"):
                if not (hasattr(self, "chat_display") and self.chat_display.winfo_exists()): return
                label = tk.Label(self.chat_display, bg="#181825")
                # Fix scroll interception
                label.bind("<MouseWheel>", self._delegate_scroll)
                label.bind("<Button-4>", self._delegate_scroll)
                label.bind("<Button-5>", self._delegate_scroll)
                
                self._append(sender, "", is_me=is_me, timestamp=ts, mid=fid)
                try:
                    self.chat_display.configure(state="normal")
                    self.chat_display.window_create(tk.END, window=label)
                    self.chat_display.insert(tk.END, "\n")
                finally:
                    if self.chat_display.winfo_exists():
                        self.chat_display.configure(state="disabled")
                
                if mime == "image/gif":
                    anim = AnimatedImage(label, data, self.chat_display)
                    self.animated_images.append(anim)
                else:
                    img = Image.open(io.BytesIO(data))
                    img.thumbnail((400, 400))
                    tk_img = ImageTk.PhotoImage(img)
                    self.images.append(tk_img)
                    label.config(image=tk_img)
            elif mime.startswith("audio/") or mime.startswith("video/") or any(filename.lower().endswith(ext) for ext in [".mp3", ".wav", ".mp4", ".mov", ".m4a"]):
                is_video = mime.startswith("video/") or any(filename.lower().endswith(e) for e in [".mp4", ".mov"])
                mtype = "Video" if is_video else "Audio"
                btn_text = f"PLAY {mtype}: {filename}"

                def _render_video(d=data, fname=filename, f_id=fid, s=sender, me=is_me, t_s=ts, do_thumb=not is_replay):
                    thumb_img = None
                    expected_channel = self.current_channel
                    if do_thumb:
                        try:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{fname}") as tmp:
                                tmp.write(d)
                                tmp_path = tmp.name
                            thumb_path = tmp_path + "_thumb.jpg"
                            result = subprocess.run(
                                ["ffmpeg", "-y", "-i", tmp_path, "-ss", "00:00:00", "-vframes", "1", thumb_path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8
                            )
                            if result.returncode == 0 and os.path.exists(thumb_path):
                                img = Image.open(thumb_path)
                                img.thumbnail((400, 225))
                                thumb_img = ImageTk.PhotoImage(img)
                                os.unlink(thumb_path)
                            os.unlink(tmp_path)
                        except Exception as e:
                            print(f"Thumb error: {e}")

                    def _display_in_ui():
                        if self.current_channel != expected_channel:
                            return  # User switched away, discard thumb/text to prevent bleeding
                        
                        self._append(s, "", is_me=me, timestamp=t_s, mid=f_id)
                        if not (hasattr(self, "chat_display") and self.chat_display.winfo_exists()): return
                        try:
                            self.chat_display.configure(state="normal")
                            if thumb_img:
                                lbl = tk.Label(self.chat_display, image=thumb_img, bg="#181825",
                                               cursor="hand2", relief=tk.FLAT)
                                lbl.image = thumb_img  # keep reference
                                lbl.bind("<Button-1>", lambda e, dd=d, fn=fname: self._save_file(fn, dd, open_after=True))
                                lbl.bind("<MouseWheel>", self._delegate_scroll)
                                self.chat_display.window_create(tk.END, window=lbl)
                                self.chat_display.insert(tk.END, "\n")
                                self.images.append(thumb_img)
                            btn = tkButton(self.chat_display, text=btn_text,
                                            command=lambda dd=d, fn=fname: self._save_file(fn, dd, open_after=True),
                                            bg="#313244", fg="#A6E3A1", font=("Arial", 12, "bold"),
                                            relief=tk.FLAT, cursor="hand2", padx=15, pady=5)
                            btn.bind("<MouseWheel>", self._delegate_scroll)
                            for b in ["<Button-2>", "<Button-3>", "<Control-Button-1>"]:
                                btn.bind(b, lambda e, fi=f_id: self._show_context_menu(e, fi))
                            self.chat_display.window_create(tk.END, window=btn)
                            self.chat_display.insert(tk.END, "\n")
                        finally:
                            if self.chat_display.winfo_exists():
                                self.chat_display.configure(state="disabled")
                                self.chat_display.see(tk.END)

                    if not do_thumb:
                        _display_in_ui()
                    else:
                        self.root.after(0, _display_in_ui)

                if is_replay:
                    _render_video() # Sync so it's inline in history
                else:
                    threading.Thread(target=_render_video, daemon=True).start()
            else:
                placeholder = f"[Preview unsupported, right-click to download: {filename}]"
                self._append(sender, placeholder, "info", is_me=is_me, timestamp=ts, mid=fid)
                # Binding to the mid in _append handles the context menu

    def _schedule_send(self, payload: dict):
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(payload)), self.loop)

    def _send_text(self):
        val = self.msg_entry.get("1.0", tk.END).strip()
        if not val: return
        
        mid = uuid.uuid4().hex[:12]
        payload = {
            "type": "text", "sender": self.username,
            "content": val, "channel": self.current_channel,
            "reply_to": self.reply_target, "msg_id": mid,
            "timestamp": time.time()
        }
        
        if self.current_pm_target:
            payload["type"] = "pm"
            payload["target"] = self.current_pm_target
            if self.current_pm_target not in self.pm_history:
                self.pm_history[self.current_pm_target] = []
                self._update_pm_list_ui()
            self.pm_history[self.current_pm_target].append(payload)
        else:
            self.channel_history[self.current_channel].append(payload)
        
        self.seen_msg_ids.add(mid)
        self._schedule_send(payload)
        self._append(self.username, val, is_me=True, mid=mid, timestamp=payload["timestamp"], reply_to=self.reply_target)
        
        self.msg_entry.delete("1.0", tk.END)
        self._cancel_reply()

    def _send_emoji(self, emoji: str):
        mid = uuid.uuid4().hex[:12]
        payload = {
            "type": "emoji", "sender": self.username,
            "content": emoji, "channel": self.current_channel,
            "reply_to": self.reply_target, "msg_id": mid,
            "timestamp": time.time()
        }
        
        if self.current_pm_target:
            payload["type"] = "pm"
            payload["target"] = self.current_pm_target
            if self.current_pm_target not in self.pm_history:
                self.pm_history[self.current_pm_target] = []
                self._update_pm_list_ui()
            self.pm_history[self.current_pm_target].append(payload)
        else:
            self.channel_history[self.current_channel].append(payload)
            
        self.seen_msg_ids.add(mid)
        self._schedule_send(payload)
        self._append(self.username, emoji, is_me=True, mid=mid, timestamp=payload["timestamp"], reply_to=self.reply_target)
        self._cancel_reply()

    def _send_file(self):
        path = filedialog.askopenfilename()
        if not path: return
        # Limit at 50MB
        if os.path.getsize(path) > 50 * 1024 * 1024:
            messagebox.showerror("File Too Large", "Maximum upload size is 50MB.")
            return
            
        filename = os.path.basename(path)
        self._setStatus(f"UPLOADING: {filename}...", "#F9E2AF")
        self.root.update_idletasks() # Force UI paint before thread lock
        
        def _upload():
            with open(path, "rb") as f:
                data_b64 = base64.b64encode(f.read()).decode("ascii")
            self._schedule_send({
                "type": "file", "sender": self.username, "filename": filename,
                "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
                "data": data_b64, "channel": self.current_channel
            })
            # Update status back to connected on the main thread after upload is done
            self.root.after(0, lambda: self._setStatus("Connected", "#585B70"))
        
        threading.Thread(target=_upload, daemon=True).start()

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    ChatClient(server_url=sys.argv[1] if len(sys.argv) > 1 else "").run()
