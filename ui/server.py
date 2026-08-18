"""Local Jarvis-style HUD served to the browser.

The voice client publishes events (assistant state and transcript lines); any
number of local browser tabs can watch them over a WebSocket. Everything stays
on 127.0.0.1 and nothing is stored.
"""
import asyncio
import json
import os
import queue
import threading
from collections import deque
from pathlib import Path

from config import Config


class NullHud:
    """Used when the HUD is disabled or its dependencies are missing."""

    active = False
    url = None

    def start(self) -> None:
        pass

    def publish(self, event: dict) -> None:
        pass

    def drain_inputs(self) -> list:
        return []


class HudServer:
    active = True

    def __init__(self, port: int | None = None):
        self.port = port or Config.HUD_PORT
        self.loop = None
        self.clients: set = set()
        self.history: deque = deque(maxlen=80)
        self._last_state: str | None = None
        self._thread: threading.Thread | None = None
        self.inputs: "queue.Queue[dict]" = queue.Queue()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, HTMLResponse
        import uvicorn

        from addons.media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

        app = FastAPI()
        html_path = Path(__file__).with_name("hud.html")
        hud = self

        @app.on_event("startup")
        async def capture_loop() -> None:
            hud.loop = asyncio.get_running_loop()

        @app.get("/")
        async def index() -> HTMLResponse:
            return HTMLResponse(html_path.read_text(encoding="utf-8"))

        @app.get("/media")
        async def media(path: str) -> FileResponse:
            # Same validation the media add-on already did server-side; this is
            # what actually lets the browser load a local file, since it can't
            # reach file:// paths itself.
            resolved = os.path.abspath(path)
            if not os.path.isfile(resolved):
                raise HTTPException(status_code=404, detail="File not found.")
            extension = os.path.splitext(resolved)[1].lower()
            if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                raise HTTPException(status_code=403, detail="Unsupported file type.")
            return FileResponse(resolved)

        @app.websocket("/ws")
        async def socket(websocket: WebSocket) -> None:
            await websocket.accept()
            hud.clients.add(websocket)
            try:
                for event in list(hud.history):
                    await websocket.send_text(json.dumps(event))
                if hud._last_state:
                    await websocket.send_text(
                        json.dumps({"type": "state", "value": hud._last_state})
                    )
                while True:
                    raw = await websocket.receive_text()
                    try:
                        message = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(message, dict) and message.get("type") == "submit":
                        hud.inputs.put(
                            {
                                "text": str(message.get("text", "")),
                                "attachments": message.get("attachments", []) or [],
                            }
                        )
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                hud.clients.discard(websocket)

        server_config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning"
        )
        self._server = uvicorn.Server(server_config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def publish(self, event: dict) -> None:
        if event.get("type") == "state":
            if event.get("value") == self._last_state:
                return
            self._last_state = event.get("value")
        else:
            self.history.append(event)
        loop = self.loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(json.dumps(event)), loop)

    def drain_inputs(self) -> list:
        """Return and clear any typed/uploaded submissions from the browser."""
        items = []
        while True:
            try:
                items.append(self.inputs.get_nowait())
            except queue.Empty:
                break
        return items

    async def _broadcast(self, payload: str) -> None:
        for client in list(self.clients):
            try:
                await client.send_text(payload)
            except Exception:
                self.clients.discard(client)


def create_hud():
    """Return a running-capable HUD, or a harmless stand-in."""
    if not Config.HUD_ENABLED:
        return NullHud()
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("[HUD] fastapi/uvicorn are not installed; continuing without the visual HUD.")
        return NullHud()
    return HudServer()
