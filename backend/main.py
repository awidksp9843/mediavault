"""
MediaVault - FastAPI Application Entry Point
WebSocket, CORS, router registration, lifecycle management.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import BIND_HOST, BACKEND_PORT, FRONTEND_PORT, logger
from backend.database import init_db
from backend.websocket_manager import ws_manager
from backend.exiftool_worker import exiftool_queue
from backend.sync_engine.integrity import check_all_workspaces
from backend.sync_engine.watcher import watcher_service
from backend.routes import files, tags, ai
from backend.ai_workers.manager import ai_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown hooks."""
    # ── Startup ──
    logger.info("MediaVault starting up...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start background model download
    async def _download_task():
        try:
            await ai_manager.download_models()
        except Exception as e:
            logger.error("Model download failed: %s", e)
    asyncio.create_task(_download_task())

    # Run integrity check on all workspaces
    try:
        check_all_workspaces()
        logger.info("Integrity check completed")
    except Exception as e:
        logger.error("Integrity check failed: %s", e)

    # Start ExifTool queue worker
    await exiftool_queue.start()

    # Start watching all registered workspaces
    from backend.database import SessionLocal, Workspace
    from pathlib import Path
    db = SessionLocal()
    try:
        workspaces = db.query(Workspace).all()
        loop = asyncio.get_event_loop()
        for ws in workspaces:
            ws_path = Path(ws.absolute_path)
            if ws_path.exists():
                watcher_service.start_watching(ws.id, ws_path, loop)
    finally:
        db.close()

    logger.info("MediaVault ready at http://%s:%d", BIND_HOST, BACKEND_PORT)

    yield

    # ── Shutdown ──
    logger.info("MediaVault shutting down...")
    watcher_service.stop_all()
    await exiftool_queue.stop()
    logger.info("Cleanup complete")


app = FastAPI(
    title="MediaVault",
    description="Local media file management dashboard with AI-powered tagging",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{FRONTEND_PORT}",
        f"http://127.0.0.1:{FRONTEND_PORT}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ──
app.include_router(files.router)
app.include_router(tags.router)
app.include_router(ai.router)


# ── WebSocket ──
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time file change notifications and AI progress."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; handle incoming messages if needed
            data = await websocket.receive_text()
            # Client can send ping/pong or commands
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ── Health Check ──
@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=BIND_HOST,
        port=BACKEND_PORT,
        reload=True,
    )
