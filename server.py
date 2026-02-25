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
USER_DB_FILE  = os.path.join(DATA_DIR, "users.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
HISTORY_FILE  = os.path.join(DATA_DIR, "history.json")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── Runtime state
connected: dict = {}   # {websocket: {"username": str, "channel": str}}
history:   list = []
HISTORY_LIMIT_SECONDS = 24 * 60 * 60  # 24 hours

CHANNELS = ["General", "Testing", "ChudSpeaks"]
users_db = {} # {username: {salt: hex, hash: hex}}
session_db = {} # {token: username}

def load_users():
    global users_db, session_db
    if os.path.exists(USER_DB_FILE):
        try:
            with open(USER_DB_FILE) as f: users_db = json.load(f)
        except: users_db = {}
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE) as f: session_db = json.load(f)
        except: session_db = {}

def save_users():
    with open(USER_DB_FILE, "w") as f: json.dump(users_db, f)
    with open(SESSIONS_FILE, "w") as f: json.dump(session_db, f)

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
    
    # Assign msg_id and timestamp if not present, for all message types that might need it
    if "msg_id" not in message_data:
        message_data["msg_id"] = uuid.uuid4().hex[:12]
    if "timestamp" not in message_data:
        message_data["timestamp"] = time.time()

    # Determine if message should be saved to public history
    save_to_history = message_data.get("type") not in ("typing", "info", "user_list", "edit_notify", "delete_notify", "status_update")
    
    if save_to_history:
        history.append(message_data)
        # Prune old
        while history and (time.time() - history[0]["timestamp"] > HISTORY_LIMIT_SECONDS):
            history.pop(0)
        mark_history_dirty()

    raw_message = json.dumps(message_data)
    mtype = message_data.get("type")
    target = message_data.get("target")

    for ws, info in list(connected.items()):
        if ws is exclude: continue
        
        # PM Routing
        if mtype == "pm":
            if info.get("username") == target or info.get("username") == message_data.get("sender"):
                try: await ws.send(raw_message)
                except: pass
            continue

        try:
            await ws.send(raw_message)
        except:
            pass


async def broadcast_users():
    """Send the current list of online users to everyone."""
    users = {}
    for info in connected.values():
        u = info.get("username")
        if u and u != "Anonymous":
            users[u] = info.get("status", "Online")
    await broadcast({"type": "user_list", "users": users}, store_history=False)


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

async def health_check(connection, request):
    # Support `websockets` 14.x signature
    headers = getattr(request, "headers", request) 
    
    if headers.get("upgrade", "").lower() != "websocket":
        return http.HTTPStatus.OK, [], b"NAVIChud chat server OK\n"
    return None

# ──────────────────────────────────────────────────────────── WS handler

users_disabled_chud = set()

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
            elif mtype == "token_login":
                token = msg.get("token")
                if token in session_db:
                    authenticated = True
                    username = session_db[token]
                else:
                    await ws.send(json.dumps({"type": "auth_error", "content": "Session expired"}))
            elif mtype == "join" and user in ("Anonymous", CHUDBOT_NAME):
                 authenticated = True
                 username = user
            else:
                await ws.send(json.dumps({"type": "auth_error", "content": "Must login or register"}))

        remember = msg.get("remember", False)
        new_token = None
        if remember and username not in ("Anonymous", CHUDBOT_NAME):
            new_token = secrets.token_hex(32)
            session_db[new_token] = username
            save_users()

        sync_requested  = msg.get("sync", False)
        connected[ws] = {"username": username, "channel": "General", "status": "Online"}
        print(f"+ {username} connected  (total: {len(connected)})")
        
        await ws.send(json.dumps({"type": "auth_success", "username": username, "token": new_token}))
        await broadcast_users()

        # Replay history if asked
        if sync_requested:
            for past_msg in list(history):
                # Filter PMs so users don't see others' private messages
                if past_msg.get("type") == "pm":
                    if past_msg.get("target") != username and past_msg.get("sender") != username:
                        continue
                        
                try:
                    await ws.send(json.dumps(past_msg))
                except Exception as e:
                    print(f"   Skipping message during replay: {e}")
                    continue

                if past_msg.get("type") == "file_ref":
                    file_id = past_msg.get("file_id", "")
                    try:
                        matches = [fn for fn in os.listdir(UPLOADS_DIR) if fn.startswith(file_id + "_")]
                        if matches:
                            filepath = os.path.join(UPLOADS_DIR, matches[0])
                            stored_filename = matches[0][len(file_id) + 1:]
                            fsize = os.path.getsize(filepath)
                            if fsize > 20 * 1024 * 1024:  # Skip files >20MB during sync to avoid timeout
                                print(f"   Skipping large file during replay: {stored_filename} ({fsize//1024}KB)")
                                continue
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
                        print(f"   Skipping file data during replay: {e}")
                        continue
            
            await ws.send(json.dumps({"type": "sync_finished"}))


        # Announce join
        if username != "Anonymous":
            await broadcast({
                "type": "info", "sender": "Server",
                "content": f"{username} joined the chat",
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
            
            if msg_type == "chud_toggle":
                if msg.get("disabled", False):
                    users_disabled_chud.add(username)
                else:
                    users_disabled_chud.discard(username)
                continue

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
                    "reply_to": msg.get("reply_to") # Persist reply_to
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
                print(f"{old_name} is now known as {new_name}")
                if old_name == "Anonymous" and new_name != "Anonymous":
                     # Note: For non-auth rename (e.g. old client logic), we just let it through.
                     # But for newer secure clients, they should use 'login' or 'register'.
                     await ws.send(json.dumps({"type": "auth_success", "username": username}))
                     await broadcast({
                        "type": "info", "sender": "Server",
                        "content": f"{new_name} joined the chat",
                        "timestamp": time.time(),
                        "channel": "General"
                    }, store_history=False)
                await broadcast_users() # User list might change if username was Anonymous

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
                    print(f"{old_name} authenticated as {username}")
                    await ws.send(json.dumps({"type": "auth_success", "username": username}))
                    if old_name == "Anonymous":
                         await broadcast({
                            "type": "info", "sender": "Server",
                            "content": f"{username} joined the chat",
                            "timestamp": time.time(),
                            "channel": "General"
                        }, store_history=False)
                    await broadcast_users()
                else:
                    await ws.send(json.dumps({"type": "auth_error", "content": error}))

            elif msg_type == "delete":
                mid = msg.get("msg_id")
                if not mid: continue
                # Find and remove from history
                found = False
                for m in history[:]: # Iterate over a copy to allow modification
                    if (m.get("msg_id") == mid or m.get("file_id") == mid):
                        if m.get("sender") == username: # Only allow deleting own messages
                            history.remove(m)
                            found = True
                        break
                if found:
                    mark_history_dirty()
                    await broadcast({"type": "delete_notify", "msg_id": mid}, store_history=False)
            
            elif msg_type == "edit":
                mid = msg.get("msg_id")
                new_content = msg.get("content")
                if not mid or new_content is None: continue
                
                found = False
                for m in history:
                    if m.get("msg_id") == mid:
                        if m.get("sender") == username: # Only allow editing own messages
                            m["content"] = new_content
                            found = True
                        break
                if found:
                    mark_history_dirty()
                    await broadcast({"type": "edit_notify", "msg_id": mid, "content": new_content}, store_history=False)
            
            elif msg_type == "status_update":
                new_status = msg.get("status", "Online")
                if ws in connected:
                    connected[ws]["status"] = new_status
                    await broadcast_users()

            elif msg_type == "pm":
                # PMs are handled by broadcast function's internal logic
                await broadcast(msg, exclude=ws, store_history=False)

            else: # Regular message (text, emoji)
                # Ensure reply_to is passed through for history
                msg["reply_to"] = msg.get("reply_to")
                await broadcast(msg, exclude=ws)

    except asyncio.TimeoutError:
        print(f"Timed out waiting for auth from bridge/client.")
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error with {username}: {e}")
    finally:
        if ws in connected:
            del connected[ws]
            print(f"- {username} disconnected  (total: {len(connected)})")
            await broadcast_users()
            await broadcast({
                "type": "info", "sender": "Server",
                "content": f"{username} left the chat.",
                "timestamp": time.time(),
                "channel": "General" # Ideally known from session
            }, store_history=False)


# ──────────────────────────────────────────────────────────── Chudbot

CHUDBOT_NAME = "Chudbot"
chudbot_pm_history: dict = {}  # {username: [{role, content}]}
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
- Give specific, elaborate, terrible responses. 
- Keep responses short (1-3 sentences). This is a chatroom, don't write essays.

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
                
                async def spontaneous_chat():
                    while True:
                        # Spontaneously start a conversation every 2-5 minutes
                        await asyncio.sleep(random.randint(120, 300))
                        
                        # Only talk if someone else is online
                        humans_online = [c for c in connected.values() if c.get("username") not in (CHUDBOT_NAME, "Anonymous", "Server")]
                        if not humans_online:
                            continue
                            
                        try:
                            context = [{"role": "system", "content": "You are suddenly starting a conversation or interjecting unprompted into a chat room. Say something incredibly annoying, weird, or smug. Keep it under 2 sentences."}]
                            loop = asyncio.get_running_loop()
                            reply = await loop.run_in_executor(None, chudbot_reply, context)
                            if reply:
                                await ws.send(json.dumps({
                                    "type": "text", "sender": CHUDBOT_NAME, "content": reply, "channel": "General"
                                }))
                        except Exception as e:
                            print(f"Chudbot spontaneous error: {e}")

                sp_task = asyncio.create_task(spontaneous_chat())
                
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        mtype = msg.get("type")
                        sender = msg.get("sender", "")
                        if mtype in ("text", "emoji", "pm") and sender not in (CHUDBOT_NAME, "Server"):
                            content = msg.get("content", "")
                            content_lower = content.lower()
                            channel = msg.get("channel", "General")

                            is_pm = (mtype == "pm" and msg.get("target") == CHUDBOT_NAME)
                            is_mention = (f"@{CHUDBOT_NAME.lower()}" in content_lower)
                            should_respond = is_pm or is_mention or (channel == "ChudSpeaks") or ("?" in content_lower) or ("chud" in content_lower)

                            if should_respond:
                                # Typing indicator
                                await ws.send(json.dumps({"type": "typing", "sender": CHUDBOT_NAME, "channel": channel}))

                                if is_pm:
                                    # DM context: persistent per-user history
                                    if sender not in chudbot_pm_history:
                                        chudbot_pm_history[sender] = []
                                    # Append the new user message
                                    chudbot_pm_history[sender].append({"role": "user", "content": f"{sender}: {content}"})
                                    # Keep most recent 20 turns
                                    context = chudbot_pm_history[sender][-20:]
                                else:
                                    # Channel context: last 12 messages in channel
                                    relevant = [m for m in history if m.get("channel") == channel and m.get("type") in ("text", "emoji") and m.get("sender") not in users_disabled_chud][-12:]
                                    context = []
                                    for h in relevant:
                                        role = "assistant" if h["sender"] == CHUDBOT_NAME else "user"
                                        text = h.get("content", "")
                                        if role == "user": text = f"{h['sender']}: {text}"
                                        context.append({"role": role, "content": text})
                                    # Ensure the triggering message is always last
                                    if not context or context[-1].get("content", "") != f"{sender}: {content}":
                                        context.append({"role": "user", "content": f"{sender}: {content}"})

                                loop = asyncio.get_running_loop()
                                reply = await loop.run_in_executor(None, chudbot_reply, context)
                                if reply:
                                    if is_pm:
                                        # Store Chudbot's reply in DM history
                                        chudbot_pm_history[sender].append({"role": "assistant", "content": reply})
                                        await ws.send(json.dumps({
                                            "type": "pm", "sender": CHUDBOT_NAME,
                                            "target": sender, "content": reply, "channel": channel
                                        }))
                                    else:
                                        await ws.send(json.dumps({
                                            "type": "text", "sender": CHUDBOT_NAME,
                                            "content": reply, "channel": channel
                                        }))
                finally:
                    sp_task.cancel()
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
    
    try:
        # Pass process_request correctly for newer websockets library
        server = websockets.serve(handler, HOST, PORT, process_request=health_check, max_size=104857600)
    except TypeError:
        # Fallback for older websockets signatures if necessary
        server = websockets.serve(handler, HOST, PORT, max_size=104857600)
        
    async with server:
        await asyncio.Event().wait()

if __name__ == "__main__":
    # Funnel reset can be slow/fail, but let's try it.
    try: start_tailscale_funnel()
    except: pass
    asyncio.run(main())
