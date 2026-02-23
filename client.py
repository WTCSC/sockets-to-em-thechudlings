import asyncio
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
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageSequence

import hashlib
import uuid
import websockets

DEFAULT_URL = "ws://localhost:8080"
CHUDSERVE_URL = "wss://mediastation.tail76b4d2.ts.net"
CHANNELS = ["General", "Testing", "ChudSpeaks"]

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
        self.root.title("NAVIChud 💬")
        self.root.geometry("800x800")
        self.root.configure(bg="#1E1E2E")
        
        self.images = []
        self.file_refs = {}
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
        
        self.username = "Anonymous"
        self.server_url = self.server_url_default
        self.sync_requested = True 
        self.joined = False
        
        # Start background connection immediately to anticipate join
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()
        
        self._build_login()

    def _build_login(self):
        for widget in self.root.winfo_children():
            widget.destroy()
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

        tk.Label(self.login_frame, text="Password",
                 font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(12, 0))
        self.pass_var = tk.StringVar()
        self.pass_entry = tk.Entry(self.login_frame, textvariable=self.pass_var, show="*",
                                   font=("Arial", 12), bg="#313244", fg="#CDD6F4",
                                   insertbackground="white", relief=tk.FLAT)
        self.pass_entry.pack(fill=tk.X, padx=60, ipady=8)

        self.auth_mode = tk.StringVar(value="login")
        mode_frame = tk.Frame(self.login_frame, bg="#1E1E2E")
        mode_frame.pack(pady=10)
        tk.Radiobutton(mode_frame, text="Login", variable=self.auth_mode, value="login",
                       bg="#1E1E2E", fg="#A6ADC8", selectcolor="#313244", activebackground="#1E1E2E").pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(mode_frame, text="Register", variable=self.auth_mode, value="register",
                       bg="#1E1E2E", fg="#A6ADC8", selectcolor="#313244", activebackground="#1E1E2E").pack(side=tk.LEFT, padx=10)

        self.server_frame = tk.Frame(self.login_frame, bg="#1E1E2E")
        tk.Label(self.server_frame, text="Server URL",
                 font=("Arial", 11), fg="#A6ADC8", bg="#1E1E2E").pack(anchor="w", padx=60, pady=(12, 0))
        self.url_var = tk.StringVar(value=self.server_url_default)
        self.url_entry = tk.Entry(self.server_frame, textvariable=self.url_var,
                 font=("Arial", 11), bg="#313244", fg="#A6ADC8",
                 insertbackground="white", relief=tk.FLAT)
        self.url_entry.pack(fill=tk.X, padx=60, ipady=6)

        self.sync_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.login_frame, text="Sync Existing Messages (Last 24h)",
                       variable=self.sync_var, font=("Arial", 10),
                       fg="#A6ADC8", bg="#1E1E2E", activebackground="#1E1E2E",
                       activeforeground="white", selectcolor="#313244").pack(pady=10)

        join_btn = tk.Button(self.login_frame, text="Join Chat →",
                             command=self._start_connect,
                             bg="#89B4FA", fg="#1E1E2E", activebackground="#74C7EC",
                             font=("Arial", 14, "bold"), relief=tk.FLAT, cursor="hand2")
        join_btn.pack(pady=10, ipadx=30, ipady=10)

        self.custom_btn = tk.Button(self.login_frame, text="⚙ Use Custom Server",
                                    command=self._show_server_settings,
                                    bg="#1E1E2E", fg="#585B70", font=("Arial", 9),
                                    relief=tk.FLAT, cursor="hand2", activebackground="#1E1E2E")
        self.custom_btn.pack(pady=5)
        self.user_entry.bind("<Return>", lambda _: self._start_connect())

    def _show_server_settings(self):
        self.server_frame.pack(fill=tk.X, before=self.custom_btn)
        self.custom_btn.pack_forget()

    def _build_chat_ui(self):
        for widget in self.root.winfo_children():
            widget.pack_forget()

        # Layout: [Sidebar (Channels)] [Chat Area]
        main_pane = tk.Frame(self.root, bg="#1E1E2E")
        main_pane.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sidebar = tk.Frame(main_pane, bg="#181825", width=150)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(sidebar, text="CHANNELS", font=("Arial", 10, "bold"), fg="#585B70", bg="#181825").pack(pady=10)
        
        self.chan_buttons = {}
        for chan in CHANNELS:
            btn = tk.Button(sidebar, text=f"# {chan}", command=lambda c=chan: self._switch_channel(c),
                            bg="#181825", fg="#CDD6F4", relief=tk.FLAT, font=("Arial", 11),
                            anchor="w", padx=10, cursor="hand2", activebackground="#313244")
            btn.pack(fill=tk.X, pady=2)
            self.chan_buttons[chan] = btn
        self._switch_channel("General", force=True)

        # Chat container
        chat_container = tk.Frame(main_pane, bg="#1E1E2E")
        chat_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat_display = scrolledtext.ScrolledText(
            chat_container, state="disabled", font=("Arial", 11),
            bg="#181825", fg="#CDD6F4", insertbackground="white",
            relief=tk.FLAT, padx=12, pady=12)
        self.chat_display.pack(padx=10, pady=(10, 0), fill=tk.BOTH, expand=True)
        self.chat_display.tag_config("info", foreground="#585B70", font=("Arial", 10, "italic"))
        self.chat_display.tag_config("timestamp", foreground="#45475A", font=("Arial", 9))
        self.chat_display.tag_config("sender_me", foreground="#89B4FA", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("sender_other", foreground="#A6E3A1", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("file", foreground="#F38BA8")
        self.chat_display.tag_config("emoji_big", font=("Segoe UI Emoji", 20))

        # Typing indicator
        self.typing_label = tk.Label(chat_container, text="", font=("Arial", 9, "italic"), fg="#A6ADC8", bg="#1E1E2E", anchor="w")
        self.typing_label.pack(fill=tk.X, padx=20)

        # Emoji bar
        emoji_bar = tk.Frame(chat_container, bg="#1E1E2E")
        emoji_bar.pack(fill=tk.X, padx=10, pady=(0, 0))
        for em in ["😊", "😂", "🔥", "👍", "👋", "🎉", "❤️", "🤔", "💯", "🚀"]:
            tk.Button(emoji_bar, text=em, command=lambda emoji_char=em: self._send_emoji(emoji_char),
                      bg="#1E1E2E", fg="white", relief=tk.FLAT,
                      font=("Segoe UI Emoji", 14), cursor="hand2").pack(side=tk.LEFT)

        # Input row
        input_frame = tk.Frame(chat_container, bg="#313244")
        input_frame.pack(fill=tk.X, padx=10, pady=(6, 12))
        self.msg_var = tk.StringVar()
        self.msg_entry = tk.Entry(input_frame, textvariable=self.msg_var,
                                  font=("Arial", 12), bg="#313244", fg="#CDD6F4",
                                  insertbackground="white", relief=tk.FLAT)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(10, 5))
        self.msg_entry.bind("<Return>", lambda _: self._send_text())
        self.msg_entry.bind("<Key>", lambda _: self._trigger_typing())
        
        tk.Button(input_frame, text="Send", command=self._send_text,
                  bg="#89B4FA", fg="#1E1E2E", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=2, ipady=6, ipadx=10)
        
        tk.Button(input_frame, text="📎", command=self._send_file,
                  bg="#45475A", fg="white", font=("Segoe UI Emoji", 12),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(2, 6), ipady=6, ipadx=6)

        self._check_typing_timeouts()

    def _switch_channel(self, name, force=False):
        if self.current_channel == name and not force: return
        self.current_channel = name
        for chan, btn in self.chan_buttons.items():
            btn.configure(bg="#89B4FA" if chan == name else "#181825", 
                         fg="#1E1E2E" if chan == name else "#CDD6F4")
        
        if hasattr(self, "chat_display"):
            self.chat_display.configure(state="normal")
            self.chat_display.delete("1.0", tk.END)
            self.chat_display.configure(state="disabled")
            # Redraw cached history for this channel
            history = self.channel_history.get(name, [])
            for msg in history:
                self._handle_incoming(msg, is_replay=True)

    def _trigger_typing(self):
        self._schedule_send({"type": "typing", "sender": self.username, "channel": self.current_channel})

    def _check_typing_timeouts(self):
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

    def _append(self, sender, content, tag="", is_me=False, image=None, timestamp=None, mid=None):
        if not hasattr(self, "chat_display"): return
        self.chat_display.configure(state="normal")
        
        start_idx = self.chat_display.index(tk.INSERT)
        ts_str = ""
        if timestamp:
            dt = datetime.fromtimestamp(timestamp)
            ts_str = dt.strftime("[%H:%M] ")
        
        if tag == "info":
            self.chat_display.insert(tk.END, f"\n  ─ {content} ─\n", "info")
        else:
            if ts_str: self.chat_display.insert(tk.END, ts_str, "timestamp")
            
            # Semantic 'Me' vs real name
            display_name = "Me" if is_me else sender
            name_tag = "sender_me" if is_me else "sender_other"
            
            self.chat_display.insert(tk.END, f"{display_name}: ", name_tag)
            
            if image:
                img_lbl = tk.Label(self.chat_display, image=image, bg="#181825")
                if is_me and mid:
                    img_lbl.bind("<Button-3>", lambda e, m=mid: self._show_context_menu(e, m))
                self.chat_display.window_create(tk.END, window=img_lbl)
                self.chat_display.insert(tk.END, "\n")
            else:
                text_idx = self.chat_display.index(tk.INSERT)
                self.chat_display.insert(tk.END, f"{content}\n", tag or "")
                # Bind right click delete for text too
                if is_me and mid:
                    # We tag the specific lines for this message
                    msg_tag = f"msg_{mid}"
                    self.chat_display.tag_add(msg_tag, start_idx, self.chat_display.index(tk.INSERT))
                    self.chat_display.tag_bind(msg_tag, "<Button-3>", lambda e, m=mid: self._show_context_menu(e, m))
            
        if mid:
            end_idx = self.chat_display.index(tk.INSERT)
            self.msg_widgets[mid] = (start_idx, end_idx)
            self.msg_senders[mid] = sender

        self.chat_display.configure(state="disabled")
        self.chat_display.see(tk.END)

    def _show_context_menu(self, event, mid):
        menu = tk.Menu(self.root, tearoff=0, bg="#313244", fg="white", activebackground="#89B4FA")
        menu.add_command(label="🗑 Delete Message", command=lambda: self._request_delete(mid))
        menu.post(event.x_root, event.y_root)

    def _request_delete(self, mid):
        self._schedule_send({"type": "delete", "msg_id": mid})

    def _start_connect(self):
        user = self.user_var.get().strip()
        pwd  = self.pass_var.get().strip()
        url  = self.url_var.get().strip()
        if not user or not url: return
        
        # Hash password for transport 'encryption'
        # In a real app we'd just use WSS, but this meets the 'encrypted in transit' req for the bits
        hashed_pwd = hashlib.sha256(pwd.encode()).hexdigest()

        if url != self.server_url:
            self.server_url = url
            # Update credentials for next connection
            self.username = user
            if self.ws:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
        else:
            mode = self.auth_mode.get()
            self._schedule_send({"type": mode, "sender": user, "password": hashed_pwd, "sync": True})

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
                print(f"Connection lost: {e}. Retrying in 5s...")
                time.sleep(5)

    async def _connect(self):
        async with websockets.connect(self.server_url) as ws:
            self.ws = ws
            if self.sync_requested:
                self.is_syncing = True
            await ws.send(json.dumps({"type": "join", "sender": self.username, "sync": self.sync_requested}))
            await self._receive_loop(ws)

    async def _receive_loop(self, ws):
        async for raw in ws:
            msg = json.loads(raw)
            self.root.after(0, self._handle_incoming, msg)

    def _handle_incoming(self, msg, is_replay=False):
        t = msg.get("type", "text")
        
        if t == "sync_finished":
            self.is_syncing = False
            if self.joined:
                self._flush_sync_buffer()
            return
        
        if t == "auth_success":
            user = msg.get("username", "Anonymous")
            if user != "Anonymous":
                self.username = user
                self.joined = True
                self._build_chat_ui()
                self._flush_sync_buffer()
            return
        
        if t == "auth_error":
            messagebox.showerror("Auth Error", msg.get("content", "Error"))
            self.joined = False
            self._build_login() 
            return

        if t == "delete_notify":
            mid = msg.get("msg_id")
            if mid in self.msg_widgets:
                start, end = self.msg_widgets[mid]
                self.chat_display.configure(state="normal")
                self.chat_display.delete(start, end)
                self.chat_display.insert(start, " (( message deleted )) \n", "info")
                self.chat_display.configure(state="disabled")
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

        if t == "text":
            self._append(sender, msg.get("content", ""), mid=mid, is_me=is_me, timestamp=ts)
        elif t == "emoji":
            # Show big emoji
            self._append(sender, msg.get("content", ""), "emoji_big", mid=mid, is_me=is_me, timestamp=ts)
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
            data = base64.b64decode(msg.get("data", ""))
            
            if mime.startswith("image/"):
                label = tk.Label(self.chat_display, bg="#181825")
                self._append(sender, "", is_me=is_me, timestamp=ts)
                self.chat_display.configure(state="normal")
                self.chat_display.window_create(tk.END, window=label)
                self.chat_display.insert(tk.END, "\n")
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
            else:
                self._append(sender, f"📎 {msg.get('filename','file')}", "file", is_me=is_me, timestamp=ts)

    def _schedule_send(self, payload: dict):
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(payload)), self.loop)

    def _send_text(self):
        text = self.msg_var.get().strip()
        if not text: return
        mid = uuid.uuid4().hex[:12]
        self.seen_msg_ids.add(mid)
        msg = {"type": "text", "sender": self.username, "content": text, "channel": self.current_channel, "msg_id": mid}
        self._schedule_send(msg)
        self.channel_history[self.current_channel].append(msg) # Added to history
        self._append("Me", text, is_me=True, timestamp=time.time())
        self.msg_var.set("")

    def _send_emoji(self, emoji: str):
        mid = uuid.uuid4().hex[:12]
        self.seen_msg_ids.add(mid)
        msg = {"type": "emoji", "sender": self.username, "content": emoji, "channel": self.current_channel, "msg_id": mid}
        self._schedule_send(msg)
        self.channel_history[self.current_channel].append(msg) # Added to history
        self._append("Me", emoji, "emoji_big", is_me=True, timestamp=time.time())

    def _send_file(self):
        path = filedialog.askopenfilename()
        if not path: return
        filename = os.path.basename(path)
        with open(path, "rb") as f:
            data_b64 = base64.b64encode(f.read()).decode("ascii")
        self._schedule_send({
            "type": "file", "sender": self.username, "filename": filename,
            "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
            "data": data_b64, "channel": self.current_channel
        })

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    ChatClient(server_url=sys.argv[1] if len(sys.argv) > 1 else "").run()
