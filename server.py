"""
NAVIChud Chat Server
Uses asyncio + websockets so it can be exposed publicly via Tailscale Funnel.

Usage:
    python3 server.py

Then in a separate terminal:
    tailscale funnel --bg 8080
Clients connect to wss://pop-os.tail76b4d2.ts.net  (or ws://localhost:8080 locally)
"""

import asyncio
import http
import json
import time
import websockets

HOST = "0.0.0.0"
PORT = 8080

# {websocket: username}
connected: dict = {}

# Message history: [{"type":..., "sender":..., "content":..., "timestamp":...}, ...]
history: list = []
HISTORY_LIMIT_SECONDS = 24 * 60 * 60  # 24 hours


async def health_check(connection, request):
    """Return 200 OK for plain HTTP probes (e.g. Tailscale Funnel health checks).
    Only real WebSocket upgrades are passed through to the handler."""
    if request.headers.get("upgrade", "").lower() != "websocket":
        return connection.respond(http.HTTPStatus.OK, "NAVIChud chat server OK\n")


async def broadcast(message: str, exclude=None, store_history=True):
    """Send a JSON string to all connected clients except the sender."""
    if store_history:
        data = json.loads(message)
        if data.get("type") in ["text", "emoji", "file"]:
            data["timestamp"] = time.time()
            history.append(data)
            # Prune immediately if needed (more robustly handled by cleanup task)
            while history and (time.time() - history[0]["timestamp"] > HISTORY_LIMIT_SECONDS):
                history.pop(0)
        message = json.dumps(data) # Update with timestamp

    for ws in list(connected):
        if ws is exclude:
            continue
        try:
            await ws.send(message)
        except Exception:
            pass  # will be cleaned up by handler


async def cleanup_history():
    """Periodically remove messages older than 24 hours."""
    while True:
        now = time.time()
        while history and (now - history[0]["timestamp"] > HISTORY_LIMIT_SECONDS):
            history.pop(0)
        await asyncio.sleep(600)  # Check every 10 minutes


async def handler(ws):
    """Handle one client connection for its lifetime."""
    username = None
    try:
        # First frame must be the join message: {"type":"join","sender":"<name>", "sync": bool}
        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        msg = json.loads(raw)
        username = msg.get("sender", "Anonymous")
        sync_requested = msg.get("sync", False)
        
        connected[ws] = username
        print(f"+ {username} connected  (total: {len(connected)})")

        # Sync history if requested
        if sync_requested:
            for past_msg in history:
                try:
                    await ws.send(json.dumps(past_msg))
                except Exception:
                    break

        # Notify everyone
        join_note = json.dumps({
            "type": "info",
            "sender": "Server",
            "content": f"{username} joined the chat 👋"
        })
        await broadcast(join_note, store_history=False)

        # Relay loop
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "text")
            print(f"  [{username}] {msg_type}: "
                  f"{msg.get('filename') or msg.get('content','')[:60]}")

            # Relay to everyone else as-is
            await broadcast(raw, exclude=ws)

    except asyncio.TimeoutError:
        print("Timed out waiting for join message.")
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error with {username}: {e}")
    finally:
        if ws in connected:
            del connected[ws]
        if username:
            print(f"- {username} disconnected  (total: {len(connected)})")
            leave_note = json.dumps({
                "type": "info",
                "sender": "Server",
                "content": f"{username} left the chat."
            })
            await broadcast(leave_note)


async def main():
    print(f"🚀 Chat server listening on ws://{HOST}:{PORT}")
    print(f"   Expose publicly with:  tailscale funnel --bg {PORT}")
    print(f"   Public URL:            wss://pop-os.tail76b4d2.ts.net\n")
    
    # Start cleanup task
    asyncio.create_task(cleanup_history())
    
    async with websockets.serve(handler, HOST, PORT, process_request=health_check):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
