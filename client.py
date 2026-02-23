import asyncio
import base64
import io
import json
import mimetypes
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk

import websockets

DEFAULT_URL = "ws://localhost:8080"
CHUDSERVE_URL = "wss://mediastation.tail76b4d2.ts.net"


class ChatClient:
    def __init__(self, server_url: str = ""):
        self.server_url_default = server_url or DEFAULT_URL
        self.ws = None
        self.loop = None                   # asyncio loop in background thread
        self.root = tk.Tk()
        self.root.title("NAVIChud 💬")
        self.root.geometry("600x800")
        self.root.configure(bg="#1E1E2E")
        self.images = [] # Keep references to prevent garbage collection
        self._build_login()

    # ──────────────────────────────────────────────────────────── login screen
    def _build_login(self):
        self.login_frame = tk.Frame(self.root, bg="#1E1E2E")
        self.login_frame.pack(expand=True)

        tk.Label(self.login_frame, text="NAVIChud 💬",
                 font=("Arial", 24, "bold"), fg="#CDD6F4", bg="#1E1E2E").pack(pady=(30, 8))
        
        tk.Label(self.login_frame, text="Username",
                 font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60)
        self.user_var = tk.StringVar()
        self.user_entry = tk.Entry(self.login_frame, textvariable=self.user_var,
                                   font=("Arial", 12), bg="#313244", fg="#CDD6F4",
                                   insertbackground="white", relief=tk.FLAT)
        self.user_entry.pack(fill=tk.X, padx=60, ipady=8)

        tk.Label(self.login_frame, text="Server URL",
                 font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(12, 0))
        self.url_var = tk.StringVar(value=self.server_url_default)
        self.url_entry = tk.Entry(self.login_frame, textvariable=self.url_var,
                 font=("Arial", 11), bg="#313244", fg="#A6ADC8",
                 insertbackground="white", relief=tk.FLAT)
        self.url_entry.pack(fill=tk.X, padx=60, ipady=6)

        # Sync Checkbox
        self.sync_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.login_frame, text="Sync Existing Messages (Last 24h)",
                       variable=self.sync_var, font=("Arial", 10),
                       fg="#A6ADC8", bg="#1E1E2E", activebackground="#1E1E2E",
                       activeforeground="white", selectcolor="#313244").pack(pady=10)

        # Quick Select Server Options
        server_opts = tk.Frame(self.login_frame, bg="#1E1E2E")
        server_opts.pack(pady=10)

        tk.Label(server_opts, text="Quick Select:", font=("Arial", 10), fg="#A6ADC8", bg="#1E1E2E").pack(side=tk.LEFT, padx=5)
        
        tk.Button(server_opts, text="Local", command=lambda: self.url_var.set(DEFAULT_URL),
                  bg="#45475A", fg="white", font=("Arial", 9), relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=2)
        
        tk.Button(server_opts, text="Chudserve", command=lambda: self.url_var.set(CHUDSERVE_URL),
                  bg="#F38BA8", fg="#1E1E2E", font=("Arial", 9, "bold"), relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=2)

        join_btn = tk.Button(self.login_frame, text="Join Chat →",
                             command=self._start_connect,
                             bg="#89B4FA", fg="#1E1E2E", activebackground="#74C7EC",
                             font=("Arial", 14, "bold"), relief=tk.FLAT, cursor="hand2")
        join_btn.pack(pady=24, ipadx=30, ipady=10)
        self.user_entry.bind("<Return>", lambda _: self._start_connect())

    # ──────────────────────────────────────────────────────────── chat screen
    def _build_chat_ui(self):
        self.login_frame.pack_forget()

        self.chat_display = scrolledtext.ScrolledText(
            self.root, state="disabled", font=("Arial", 11),
            bg="#181825", fg="#CDD6F4", insertbackground="white",
            relief=tk.FLAT, padx=12, pady=12)
        self.chat_display.pack(padx=10, pady=(10, 0), fill=tk.BOTH, expand=True)
        self.chat_display.tag_config("info", foreground="#585B70", font=("Arial", 10, "italic"))
        self.chat_display.tag_config("sender_me", foreground="#89B4FA", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("sender_other", foreground="#A6E3A1", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("file", foreground="#F38BA8")
        self.chat_display.tag_config("emoji_big", font=("Segoe UI Emoji", 20))

        # Emoji bar
        emoji_bar = tk.Frame(self.root, bg="#1E1E2E")
        emoji_bar.pack(fill=tk.X, padx=10, pady=(6, 0))
        for em in ["😊", "😂", "🔥", "👍", "👋", "🎉", "❤️", "🤔", "💯", "🚀"]:
            tk.Button(emoji_bar, text=em, command=lambda emoji_char=em: self._send_emoji(emoji_char),
                      bg="#1E1E2E", fg="white", relief=tk.FLAT,
                      font=("Segoe UI Emoji", 14), cursor="hand2").pack(side=tk.LEFT)

        # Input row
        input_frame = tk.Frame(self.root, bg="#313244")
        input_frame.pack(fill=tk.X, padx=10, pady=12)
        self.msg_var = tk.StringVar()
        self.msg_entry = tk.Entry(input_frame, textvariable=self.msg_var,
                                  font=("Arial", 12), bg="#313244", fg="#CDD6F4",
                                  insertbackground="white", relief=tk.FLAT)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(10, 5))
        self.msg_entry.bind("<Return>", lambda _: self._send_text())
        
        tk.Button(input_frame, text="Send", command=self._send_text,
                  bg="#89B4FA", fg="#1E1E2E", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=2, ipady=6, ipadx=10)
        
        tk.Button(input_frame, text="📎", command=self._send_file,
                  bg="#45475A", fg="white", font=("Segoe UI Emoji", 12),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(2, 6), ipady=6, ipadx=6)

    def _append(self, sender, content, tag="", is_me=False, image=None):
        self.chat_display.configure(state="normal")
        if tag == "info":
            self.chat_display.insert(tk.END, f"\n  ─ {content} ─\n", "info")
        else:
            name_tag = "sender_me" if is_me else "sender_other"
            self.chat_display.insert(tk.END, f"{sender}: ", name_tag)
            if image:
                self.chat_display.window_create(tk.END, window=tk.Label(self.chat_display, image=image, bg="#181825"))
                self.chat_display.insert(tk.END, "\n")
            else:
                self.chat_display.insert(tk.END, f"{content}\n", tag or "")
        self.chat_display.configure(state="disabled")
        self.chat_display.see(tk.END)

    # ──────────────────────────────────────────────────────────── networking
    def _start_connect(self):
        user = self.user_var.get().strip()
        url  = self.url_var.get().strip()
        if not user:
            messagebox.showwarning("Missing username", "Please enter a username.")
            return
        if not url:
            messagebox.showwarning("Missing URL", "Please enter the server URL.")
            return
        self.username = user
        self.server_url = url
        self.sync_requested = self.sync_var.get()

        # Spin up asyncio event loop on a daemon thread
        self.loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()

    def _run_loop(self):
        """Runs the asyncio loop in a background thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect())

    async def _connect(self):
        try:
            async with websockets.connect(self.server_url) as ws:
                self.ws = ws
                # Send join message
                await ws.send(json.dumps({
                    "type": "join", 
                    "sender": self.username,
                    "sync": self.sync_requested
                }))
                # Switch to chat UI on the main thread
                self.root.after(0, self._build_chat_ui)
                self.root.after(0, lambda: self._append(
                    "Server", f"Connected to {self.server_url}", "info"))
                # Receive loop
                await self._receive_loop(ws)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror(
                "Connection Error", f"Could not connect:\n{e}"))

    async def _receive_loop(self, ws):
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.root.after(0, self._handle_incoming, msg)
        except websockets.exceptions.ConnectionClosed:
            self.root.after(0, lambda: self._append(
                "Server", "Disconnected from server.", "info"))
        except Exception as e:
            self.root.after(0, lambda: self._append(
                "Server", f"Error: {e}", "info"))

    def _handle_incoming(self, msg):
        t    = msg.get("type", "text")
        sender = msg.get("sender", "?")
        is_me = (sender == self.username)
        
        if t == "text":
            self._append(sender, msg.get("content", ""), is_me=is_me)
        elif t == "emoji":
            self._append(sender, msg.get("content", ""), "emoji_big", is_me=is_me)
        elif t == "info":
            self._append(sender, msg.get("content", ""), "info")
        elif t == "file":
            filename = msg.get("filename", "file")
            data_b64 = msg.get("data", "")
            mime = msg.get("mime", "")
            data = base64.b64decode(data_b64)
            
            # Save the file anyway in the background
            os.makedirs("downloads", exist_ok=True)
            save_path = os.path.join("downloads", filename)
            with open(save_path, "wb") as f:
                f.write(data)

            # Display images
            if mime.startswith("image/"):
                try:
                    img_data = io.BytesIO(data)
                    img = Image.open(img_data)
                    # Simple resize for chat viewing
                    img.thumbnail((300, 300))
                    tk_img = ImageTk.PhotoImage(img)
                    self.images.append(tk_img) # Save reference
                    self._append(sender, "", is_me=is_me, image=tk_img)
                except Exception as e:
                    print(f"Error rendering image: {e}")
                    self._append(sender, f"📎 {filename} (saved to downloads/)", "file", is_me=is_me)
            else:
                self._append(sender, f"📎 {filename} (saved to downloads/)", "file", is_me=is_me)

    # ──────────────────────────────────────────────────────────── send helpers
    def _schedule_send(self, payload: dict):
        """Thread-safe: schedule a coroutine on the background loop."""
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.ws.send(json.dumps(payload)), self.loop)

    def _send_text(self):
        text = self.msg_var.get().strip()
        if not text: return
        self._schedule_send({"type": "text", "sender": self.username, "content": text})
        self._append("Me", text, is_me=True)
        self.msg_var.set("")

    def _send_emoji(self, emoji: str):
        self._schedule_send({"type": "emoji", "sender": self.username, "content": emoji})
        self._append("Me", emoji, "emoji_big", is_me=True)

    def _send_file(self):
        path = filedialog.askopenfilename(title="Select a file to send")
        if not path: return
        size = os.path.getsize(path)
        if size > 10 * 1024 * 1024:
            messagebox.showwarning("File too large", "Max file size is 10 MB.")
            return
        filename = os.path.basename(path)
        with open(path, "rb") as f:
            data_b64 = base64.b64encode(f.read()).decode("ascii")
        mime, _ = mimetypes.guess_type(path)
        self._schedule_send({
            "type": "file",
            "sender": self.username,
            "filename": filename,
            "mime": mime or "application/octet-stream",
            "data": data_b64,
        })
        self._append("Me", f"📎 {filename} (sent)", "file", is_me=True)

    # ──────────────────────────────────────────────────────────── run
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    ChatClient(server_url=url).run()
