"""
MediaVault - WebSocket Connection Manager
Manages connections and implements 0.5s event debouncing/batching.
"""
import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket
from backend.config import logger


class ConnectionManager:
    """Manages WebSocket connections with event debouncing."""

    def __init__(self, debounce_interval: float = 0.5):
        self.active_connections: list[WebSocket] = []
        self._event_buffer: list[dict[str, Any]] = []
        self._debounce_interval = debounce_interval
        self._flush_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def _flush_buffer(self):
        """Flush accumulated events to all connected clients."""
        await asyncio.sleep(self._debounce_interval)
        async with self._lock:
            if not self._event_buffer:
                return
            batch = self._event_buffer.copy()
            self._event_buffer.clear()
            self._flush_task = None

        if not batch:
            return

        message = json.dumps({"type": "batch", "events": batch, "count": len(batch)})
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.append(connection)

        for conn in dead_connections:
            self.disconnect(conn)

    async def queue_event(self, event_type: str, data: dict[str, Any] | None = None):
        """Queue an event for debounced batch delivery."""
        async with self._lock:
            self._event_buffer.append({
                "event": event_type,
                "data": data or {},
                "timestamp": time.time(),
            })
            if (self._flush_task is None or self._flush_task.done()) and self._event_buffer:
                self._flush_task = asyncio.create_task(self._flush_buffer())

    async def broadcast_immediate(self, event_type: str, data: dict[str, Any] | None = None):
        """Send an event immediately without debouncing (for critical updates)."""
        message = json.dumps({
            "type": "single",
            "event": event_type,
            "data": data or {},
            "timestamp": time.time(),
        })
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.append(connection)
        for conn in dead_connections:
            self.disconnect(conn)


ws_manager = ConnectionManager()
