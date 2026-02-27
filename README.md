# NAVIChud Chat Application

A multi-user chat app built with Python `websockets` + `tkinter`. Accessible locally **or anywhere on the internet** via Tailscale Funnel.

## TODO:

Does someone wanna add:
- Themes?
- Change the UX?
- Add a settings menu?
- Support video playback?
- Show usernames next to media? (Currently shows "?")
- Add message editing and deleting?
- Add a "who's online" list?
- Profile Pictures?

## Quick Start

### 1. Start the Server
```bash
python3 server.py
```
Output:
```
🚀 Chat server listening on ws://0.0.0.0:8080
   Expose publicly with:  tailscale funnel --bg 8080
   Public URL:            wss://....ts.net
```

### 2. Expose to the Internet (Tailscale Funnel)
In a second terminal, run **once** (persists across reboots):
```bash
tailscale funnel --bg 8080
```
Your server is now live at `wss://...ts.net` 🌐

### 3. Start a Client

**Local machine:**
```bash
python3 client.py
# Server URL: ws://localhost:8080
```

**Connect to Chudserve:**
Select **Chudserve** in the login screen or use:
```bash
python3 client.py wss://...ts.net
```

## Features
| Feature | Details |
|---|---|
| 💬 Text chat | Multi-user, real-time |
| 😊 Emojis | One-click emoji bar |
| 📎 File transfers | Images, audio, documents (≤ 10 MB) |
| 🔒 TLS / HTTPS | Automatic via Tailscale Funnel |
| ⚠️ Error handling | Timeouts, disconnects, bad data |

### Files received from others
Saved automatically to `./downloads/` where the client is run.

## Architecture

```
client.py  ──(ws/wss)──▶  server.py :8080  ◀──(wss)──  anyone on internet
                                ▲
                     tailscale funnel --bg 8080
                     (HTTPS termination, port 443)
```

## Requirements

- Python 3.10+
- `pip install websockets`
- `tkinter` (Linux: `sudo apt install python3-tk`)
- Tailscale installed and logged in (for internet access)
