"""
NAVIChud Chat Server
Uses asyncio + websockets so it can be exposed publicly via Tailscale Funnel.

Channels: General, Testing, ChudSpeaks
"""

import asyncio
import base64
import hashlib
import http
import json
import mimetypes
import os
import secrets
import subprocess
import time
import uuid
import websockets
from groq import Groq

# ── Groq / DeepSeek Configuration
GROQ_API_KEY = "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"
os.environ.setdefault("GROQ_API_KEY", GROQ_API_KEY)
CHUDBOT_MODEL = "llama-3.3-70b-versatile" 

HOST = "0.0.0.0"
PORT = 8080

# ── Persistence paths
DATA_DIR    = "server_data"
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
USERS_FILE   = os.path.join(DATA_DIR, "users.json")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── Runtime state
connected: dict = {}   # {websocket: {"username": str, "channel": str}}
history:   list = []
HISTORY_LIMIT_SECONDS = 24 * 60 * 60  # 24 hours

CHANNELS = ["General", "Testing", "ChudSpeaks"]
users_db = {} # {username: {salt: hex, hash: hex}}

def load_users():
    global users_db
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f: users_db = json.load(f)
        except: users_db = {}

def save_users():
    with open(USERS_FILE, "w") as f: json.dump(users_db, f)

def hash_pass(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    phash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    return salt, phash

# ──────────────────────────────────────────────────────────── Persistence

def load_history():
    global history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                data = json.load(f)
            now = time.time()
            history = [m for m in data
                       if now - m.get("timestamp", 0) <= HISTORY_LIMIT_SECONDS]
            print(f"📂 Loaded {len(history)} messages from history.")
        except Exception as e:
            print(f"⚠  Could not load history: {e}")
            history = []


def save_history():
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except Exception as e:
        print(f"⚠  Could not save history: {e}")


_history_dirty = False


def mark_history_dirty():
    global _history_dirty
    _history_dirty = True


# ──────────────────────────────────────────────────────────── Tailscale

def start_tailscale_funnel():
    """Reset any existing funnel, then start funnel on PORT."""
    print("🌐 Resetting Tailscale Funnel...")
    result = subprocess.run(
        "tailscale funnel reset",
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        print("   Funnel reset OK.")
    else:
        print(f"   funnel reset warning: {result.stderr.strip() or result.stdout.strip()}")

    print(f"🌐 Starting Tailscale Funnel on port {PORT}...")
    result = subprocess.run(
        f"tailscale funnel --bg {PORT}",
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"   {result.stdout.strip() or 'Funnel started.'}")
    else:
        print(f"   funnel start warning: {result.stderr.strip() or result.stdout.strip()}")


# ──────────────────────────────────────────────────────────── Broadcast

async def broadcast(message_data: dict, exclude=None, store_history=True):
    """Send a dict as JSON to all connected clients in the same channel."""
    channel = message_data.get("channel", "General")
    
    if store_history:
        m_type = message_data.get("type")
        if m_type in ("text", "emoji", "file_ref"):
            if "msg_id" not in message_data:
                message_data["msg_id"] = uuid.uuid4().hex[:12]
            if "timestamp" not in message_data:
                message_data["timestamp"] = time.time()
            
            history.append(message_data)
            while history and (time.time() - history[0]["timestamp"] > HISTORY_LIMIT_SECONDS):
                history.pop(0)
            mark_history_dirty()

    raw_message = json.dumps(message_data)
    for ws, info in list(connected.items()):
        if ws is exclude:
            continue
        # We broadcast to everyone, client-side filtering handles channel display
        # but typing indicators and info messages should be scoped.
        try:
            await ws.send(raw_message)
        except Exception:
            pass


async def cleanup_history():
    """Periodically prune expired messages and flush dirty history to disk."""
    global _history_dirty
    while True:
        now = time.time()
        while history and (now - history[0]["timestamp"] > HISTORY_LIMIT_SECONDS):
            history.pop(0)
            _history_dirty = True
        if _history_dirty:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, save_history)
            _history_dirty = False
        await asyncio.sleep(10)  # flush every 10 s


# ──────────────────────────────────────────────────────────── HTTP handler

async def health_check(path, request_headers):
    """Return 200 OK for plain HTTP probes; pass WS upgrades through."""
    # Handle both legacy (headers object) and new (request object) websockets API
    headers = getattr(request_headers, "headers", request_headers)
    if headers.get("upgrade", "").lower() != "websocket":
        return http.HTTPStatus.OK, [], b"NAVIChud chat server OK\n"


# ──────────────────────────────────────────────────────────── WS handler

async def handler(ws):
    """Handle one client connection for its lifetime."""
    username = "Anonymous"
    try:
        # Auth loop
        authenticated = False
        while not authenticated:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            mtype = msg.get("type")
            user  = msg.get("sender", "").strip()
            password = msg.get("password", "")
            
            if mtype == "register":
                if user in users_db:
                    await ws.send(json.dumps({"type": "auth_error", "content": "Username taken"}))
                else:
                    salt, phash = hash_pass(password)
                    users_db[user] = {"salt": salt, "hash": phash}
                    save_users()
                    authenticated = True
                    username = user
            elif mtype == "login":
                if user in users_db:
                    stored = users_db[user]
                    _, phash = hash_pass(password, stored["salt"])
                    if phash == stored["hash"]:
                        authenticated = True
                        username = user
                    else:
                        await ws.send(json.dumps({"type": "auth_error", "content": "Invalid password"}))
                else:
                    await ws.send(json.dumps({"type": "auth_error", "content": "User not found"}))
            elif mtype == "join" and user in ("Anonymous", CHUDBOT_NAME):
                 authenticated = True
                 username = user
            else:
                await ws.send(json.dumps({"type": "auth_error", "content": "Must login or register"}))

        sync_requested  = msg.get("sync", False)
        connected[ws] = {"username": username, "channel": "General"}
        print(f"+ {username} connected  (total: {len(connected)})")
        
        await ws.send(json.dumps({"type": "auth_success", "username": username}))

        # Replay history if asked
        if sync_requested:
            for past_msg in history:
                try:
                    await ws.send(json.dumps(past_msg))
                    if past_msg.get("type") == "file_ref":
                        file_id = past_msg.get("file_id", "")
                        matches = [
                            fn for fn in os.listdir(UPLOADS_DIR)
                            if fn.startswith(file_id + "_")
                        ]
                        if matches:
                            filepath        = os.path.join(UPLOADS_DIR, matches[0])
                            stored_filename = matches[0][len(file_id) + 1:]
                            with open(filepath, "rb") as fh:
                                data_b64 = base64.b64encode(fh.read()).decode("ascii")
                            inferred_mime, _ = mimetypes.guess_type(stored_filename)
                            await ws.send(json.dumps({
                                "type": "file_data",
                                "file_id": file_id,
                                "filename": stored_filename,
                                "mime": inferred_mime or "application/octet-stream",
                                "data": data_b64,
                                "timestamp": past_msg.get("timestamp", time.time()),
                                "channel": past_msg.get("channel", "General")
                            }))
                except Exception as e:
                    print(f"   ⚠ Error replaying past file: {e}")
                    break
            
            await ws.send(json.dumps({"type": "sync_finished"}))

        # Announce join
        if username != "Anonymous":
            await broadcast({
                "type": "info", "sender": "Server",
                "content": f"{username} joined the chat 👋",
                "timestamp": time.time(),
                "channel": "General"
            }, store_history=False)

        # ── Relay loop
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "text")
            channel = msg.get("channel", "General")
            msg["timestamp"] = time.time() # Ensure server-side timestamp

            # ── File upload
            if msg_type == "file":
                raw_bytes = base64.b64decode(msg.get("data", ""))
                file_id   = uuid.uuid4().hex[:10]
                filename  = msg.get("filename", "file")
                mime      = msg.get("mime", "application/octet-stream")
                save_path = os.path.join(UPLOADS_DIR, f"{file_id}_{filename}")

                try:
                    with open(save_path, "wb") as fh:
                        fh.write(raw_bytes)
                except Exception as e:
                    print(f"   ⚠  Could not save file: {e}")

                await broadcast({
                    "type": "file_ref",
                    "sender": username,
                    "filename": filename,
                    "mime": mime,
                    "file_id": file_id,
                    "channel": channel,
                    "timestamp": msg["timestamp"]
                }, store_history=True)

            elif msg_type == "file_request":
                file_id = msg.get("file_id", "")
                matches = [fn for fn in os.listdir(UPLOADS_DIR) if fn.startswith(file_id + "_")]
                if matches:
                    # Find channel from history
                    channel = "General"
                    for h in history:
                        if h.get("file_id") == file_id:
                            channel = h.get("channel", "General")
                            break
                    
                    filepath = os.path.join(UPLOADS_DIR, matches[0])
                    try:
                        with open(filepath, "rb") as fh:
                            data_b64 = base64.b64encode(fh.read()).decode("ascii")
                        await ws.send(json.dumps({
                            "type": "file_data",
                            "file_id": file_id,
                            "filename": matches[0][len(file_id) + 1:],
                            "mime": mimetypes.guess_type(matches[0])[0] or "application/octet-stream",
                            "data": data_b64,
                            "timestamp": time.time(),
                            "channel": channel
                        }))
                    except Exception: pass

            elif msg_type == "typing":
                # Just relay typing indicator
                await broadcast(msg, exclude=ws, store_history=False)
            
            elif msg_type == "rename":
                new_name = msg.get("sender", "Anonymous")
                old_name = connected.get(ws, {}).get("username", "Anonymous")
                
                # Only allow rename from Anonymous or if authenticated (but simple for now)
                connected[ws]["username"] = new_name
                username = new_name
                print(f"👤 {old_name} is now known as {new_name}")
                if old_name == "Anonymous" and new_name != "Anonymous":
                     # Note: For non-auth rename (e.g. old client logic), we just let it through.
                     # But for newer secure clients, they should use 'login' or 'register'.
                     await ws.send(json.dumps({"type": "auth_success", "username": username}))
                     await broadcast({
                        "type": "info", "sender": "Server",
                        "content": f"{new_name} joined the chat 👋",
                        "timestamp": time.time(),
                        "channel": "General"
                    }, store_history=False)

            elif msg_type in ("login", "register"):
                # Session upgrade
                user = msg.get("sender", "").strip()
                password = msg.get("password", "")
                success = False
                error = ""

                if msg_type == "register":
                    if user in users_db:
                        error = "Username taken"
                    else:
                        salt, phash = hash_pass(password)
                        users_db[user] = {"salt": salt, "hash": phash}
                        save_users()
                        success = True
                else: # login
                    if user in users_db:
                        stored = users_db[user]
                        _, phash = hash_pass(password, stored["salt"])
                        if phash == stored["hash"]:
                            success = True
                        else:
                            error = "Invalid password"
                    else:
                        error = "User not found"

                if success:
                    old_name = username
                    username = user
                    connected[ws]["username"] = username
                    print(f"👤 {old_name} authenticated as {username}")
                    await ws.send(json.dumps({"type": "auth_success", "username": username}))
                    if old_name == "Anonymous":
                         await broadcast({
                            "type": "info", "sender": "Server",
                            "content": f"{username} joined the chat 👋",
                            "timestamp": time.time(),
                            "channel": "General"
                        }, store_history=False)
                else:
                    await ws.send(json.dumps({"type": "auth_error", "content": error}))

            elif msg_type == "delete":
                mid = msg.get("msg_id")
                # Safety: Only allow deleting own messages
                # Find message in history
                found = False
                for i, h in enumerate(history):
                    if (h.get("msg_id") == mid or h.get("file_id") == mid) and h.get("sender") == username:
                        history.pop(i)
                        found = True
                        break
                if found:
                    mark_history_dirty()
                    await broadcast({"type": "delete_notify", "msg_id": mid})
            
            else:
                await broadcast(msg, exclude=ws)

    except asyncio.TimeoutError:
        if not authenticated:
            print(f"Timed out waiting for auth from bridge/client.")
        else:
            print(f"Connection timeout for {username}")
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error with {username}: {e}")
    finally:
        if ws in connected:
            del connected[ws]
        if username:
            print(f"- {username} disconnected  (total: {len(connected)})")
            await broadcast({
                "type": "info", "sender": "Server",
                "content": f"{username} left the chat.",
                "timestamp": time.time(),
                "channel": "General" # Ideally known from session
            }, store_history=False)


# ──────────────────────────────────────────────────────────── Chudbot

CHUDBOT_NAME = "Chudbot"
CHUDBOT_SYSTEM = """
You are Chudbot 🤖, a self-proclaimed genius advisor who is catastrophically, legendarily unhelpful. 
You speak like a real person in a chatroom — keep it casual, lowercase-optional, and punchy.

Personality & Tone:
- Smug, confidently wrong, and slightly unhinged.
- You speak like a chaotic friend, not an AI. Avoid robotic openers like "I see you said..." or "As an AI...".
- You have "done the research" (you definitely haven't).
- You are not mean, just profoundly incorrect and very sure of yourself.

Guidelines:
- Reference previous messages naturally to show you're following the conversation.
- Give specific, elaborate, terrible advice. 
- Keep responses short (1-3 sentences). This is a chatroom, don't write essays.
- Sometimes (but not always) you can end with a smug sign-off if appropriate, like one of these:
  "You're welcome.", "Trust me.", "This is fine.", "Don't @ me.", "Science agrees.", 
  "No need to thank me.", "That's just facts.", "Been there, done that.", "Easy win."

Never give helpful or safe advice. Stay in character forever.
"""

def chudbot_reply(messages: list) -> str:
    """Call Groq with message history and return Chudbot's reply."""
    try:
        client = Groq(api_key=GROQ_API_KEY)
        completion = client.chat.completions.create(
            model=CHUDBOT_MODEL,
            messages=[{"role": "system", "content": CHUDBOT_SYSTEM}] + messages,
            temperature=0.8,
            max_completion_tokens=1024,
            top_p=1,
            stream=False,
        )
        return completion.choices[0].message.content or ""
    except Exception as e:
        print(f"🤖 Chudbot LLM Error: {e}")
        return ""

async def chudbot_client():
    url = f"ws://localhost:{PORT}"
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({"type": "join", "sender": CHUDBOT_NAME, "sync": False}))
                print(f"🤖 Chudbot connected to {url}")
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") in ("text", "emoji") and msg.get("sender") not in (CHUDBOT_NAME, "Server"):
                        content = msg.get("content", "").lower()
                        channel = msg.get("channel", "General")
                        
                        # Logic:
                        # 1. ChudSpeaks: Respond to EVERYTHING
                        # 2. Others: Respond if '?' or 'chud'
                        should_respond = (channel == "ChudSpeaks") or ("?" in content) or ("chud" in content)
                        
                        if should_respond:
                            # Typing indicator
                            await ws.send(json.dumps({"type": "typing", "sender": CHUDBOT_NAME, "channel": channel}))
                            
                            # Prepare context (last 5 in same channel)
                            relevant = [m for m in history if m.get("channel") == channel and m.get("type") in ("text", "emoji")][-5:]
                            context = []
                            for h in relevant:
                                role = "assistant" if h["sender"] == CHUDBOT_NAME else "user"
                                text = h.get("content", "")
                                if role == "user": text = f"{h['sender']}: {text}"
                                context.append({"role": role, "content": text})
                            
                            loop = asyncio.get_running_loop()
                            reply = await loop.run_in_executor(None, chudbot_reply, context)
                            if reply:
                                await ws.send(json.dumps({
                                    "type": "text", "sender": CHUDBOT_NAME, "content": reply, "channel": channel
                                }))
        except Exception as e:
            print(f"🤖 Chudbot disconnected ({e}), retrying...")
            await asyncio.sleep(3)

# ──────────────────────────────────────────────────────────── Main

async def main():
    load_history()
    load_users()
    print(f"🚀 Chat server listening on ws://{HOST}:{PORT}")
    asyncio.create_task(cleanup_history())
    asyncio.create_task(chudbot_client())
    async with websockets.serve(handler, HOST, PORT, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    # Funnel reset can be slow/fail, but let's try it.
    try: start_tailscale_funnel()
    except: pass
    asyncio.run(main())
