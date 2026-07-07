"""
MediaVault - Watchdog File System Watcher
Monitors workspace directories for changes with self-modification blacklist
to prevent infinite loops from ExifTool writes.
"""
import asyncio
import threading
import time
from pathlib import Path
from typing import Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from backend.config import ALL_SUPPORTED_EXTENSIONS, get_media_type, logger
from backend.database import File, Workspace, SessionLocal
from backend.scanner import scan_file
from backend.websocket_manager import ws_manager


class SelfModificationBlacklist:
    """
    Thread-safe blacklist to prevent Watchdog from triggering
    on files that we ourselves are modifying (e.g., ExifTool writes).
    """

    def __init__(self, expiry_seconds: float = 5.0):
        self._blacklist: dict[str, float] = {}
        self._lock = threading.Lock()
        self._expiry = expiry_seconds

    def add(self, file_path: Path):
        """Register a file path as being modified by us."""
        with self._lock:
            self._blacklist[str(file_path.resolve())] = time.time()

    def remove(self, file_path: Path):
        """Remove a file path from the blacklist."""
        with self._lock:
            self._blacklist.pop(str(file_path.resolve()), None)

    def is_blacklisted(self, file_path: Path) -> bool:
        """Check if a file path is currently blacklisted (self-modified)."""
        key = str(file_path.resolve())
        with self._lock:
            if key in self._blacklist:
                # Auto-expire old entries
                if time.time() - self._blacklist[key] > self._expiry:
                    del self._blacklist[key]
                    return False
                return True
        return False

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, t in self._blacklist.items() if now - t > self._expiry]
            for k in expired:
                del self._blacklist[k]


# Global blacklist instance
blacklist = SelfModificationBlacklist()


class MediaFileHandler(FileSystemEventHandler):
    """Handle file system events for media files in a workspace."""

    def __init__(self, workspace_id: int, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.workspace_id = workspace_id
        self._loop = loop

    def _is_supported(self, path: str) -> bool:
        """Check if file has a supported media extension."""
        return Path(path).suffix.lower() in ALL_SUPPORTED_EXTENSIONS

    def _schedule_async(self, coro):
        """Schedule an async coroutine from the sync watchdog thread."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def on_created(self, event: FileSystemEvent):
        if event.is_directory or not self._is_supported(event.src_path):
            return
        file_path = Path(event.src_path)
        if blacklist.is_blacklisted(file_path):
            return
        logger.debug("File created: %s", event.src_path)
        self._schedule_async(self._handle_created(file_path))

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory or not self._is_supported(event.src_path):
            return
        file_path = Path(event.src_path)
        if blacklist.is_blacklisted(file_path):
            return
        logger.debug("File deleted: %s", event.src_path)
        self._schedule_async(self._handle_deleted(file_path))

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or not self._is_supported(event.src_path):
            return
        file_path = Path(event.src_path)
        if blacklist.is_blacklisted(file_path):
            return
        logger.debug("File modified: %s", event.src_path)
        self._schedule_async(self._handle_modified(file_path))

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return
        src_supported = self._is_supported(event.src_path)
        dest_supported = self._is_supported(event.dest_path)
        if not src_supported and not dest_supported:
            return
        logger.debug("File moved: %s -> %s", event.src_path, event.dest_path)
        self._schedule_async(
            self._handle_moved(Path(event.src_path), Path(event.dest_path))
        )

    async def _handle_created(self, file_path: Path):
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            if workspace:
                record = scan_file(file_path, workspace, db)
                if record:
                    await ws_manager.queue_event("file_created", {
                        "file_id": record.id,
                        "filename": record.filename,
                        "path": record.relative_path,
                    })
        finally:
            db.close()

    async def _handle_deleted(self, file_path: Path):
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            if not workspace:
                return
            workspace_path = Path(workspace.absolute_path)
            try:
                rel = file_path.relative_to(workspace_path).as_posix()
            except ValueError:
                return
            record = db.query(File).filter(
                File.workspace_id == self.workspace_id,
                File.relative_path == rel,
                File.is_deleted == False,
            ).first()
            if record:
                record.is_deleted = True
                db.commit()
                await ws_manager.queue_event("file_deleted", {
                    "file_id": record.id,
                    "filename": record.filename,
                })
        finally:
            db.close()

    async def _handle_modified(self, file_path: Path):
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            if not workspace:
                return
            workspace_path = Path(workspace.absolute_path)
            try:
                rel = file_path.relative_to(workspace_path).as_posix()
            except ValueError:
                return
            record = db.query(File).filter(
                File.workspace_id == self.workspace_id,
                File.relative_path == rel,
                File.is_deleted == False,
            ).first()
            if record:
                stat = file_path.stat()
                record.size = stat.st_size
                from backend.scanner import partial_hash
                record.file_hash = partial_hash(file_path)
                db.commit()
                await ws_manager.queue_event("file_modified", {
                    "file_id": record.id,
                    "filename": record.filename,
                })
        except Exception as e:
            logger.error("Handle modified failed: %s", e)
        finally:
            db.close()

    async def _handle_moved(self, src_path: Path, dest_path: Path):
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            if not workspace:
                return
            workspace_path = Path(workspace.absolute_path)
            try:
                old_rel = src_path.relative_to(workspace_path).as_posix()
            except ValueError:
                return
            record = db.query(File).filter(
                File.workspace_id == self.workspace_id,
                File.relative_path == old_rel,
            ).first()
            if record:
                try:
                    new_rel = dest_path.relative_to(workspace_path).as_posix()
                    record.relative_path = new_rel
                    record.filename = dest_path.name
                    record.extension = dest_path.suffix.lower()
                    record.media_type = get_media_type(dest_path.suffix.lower()) or record.media_type
                    record.is_deleted = False
                    db.commit()
                    await ws_manager.queue_event("file_moved", {
                        "file_id": record.id,
                        "old_path": old_rel,
                        "new_path": new_rel,
                    })
                except ValueError:
                    # Moved out of workspace
                    record.is_deleted = True
                    db.commit()
                    await ws_manager.queue_event("file_deleted", {
                        "file_id": record.id,
                        "filename": record.filename,
                    })
        finally:
            db.close()


class WatcherService:
    """Manages Watchdog observers for all active workspaces."""

    def __init__(self):
        self._observers: dict[int, Observer] = {}

    def start_watching(self, workspace_id: int, workspace_path: Path, loop: asyncio.AbstractEventLoop):
        """Start watching a workspace directory."""
        if workspace_id in self._observers:
            logger.warning("Already watching workspace %d", workspace_id)
            return

        handler = MediaFileHandler(workspace_id, loop)
        observer = Observer()
        observer.schedule(handler, str(workspace_path), recursive=True)
        observer.daemon = True
        observer.start()
        self._observers[workspace_id] = observer
        logger.info("Started watching workspace %d: %s", workspace_id, workspace_path)

    def stop_watching(self, workspace_id: int):
        """Stop watching a workspace directory."""
        observer = self._observers.pop(workspace_id, None)
        if observer:
            observer.stop()
            observer.join(timeout=5)
            logger.info("Stopped watching workspace %d", workspace_id)

    def stop_all(self):
        """Stop all watchers."""
        for wid in list(self._observers.keys()):
            self.stop_watching(wid)


watcher_service = WatcherService()
