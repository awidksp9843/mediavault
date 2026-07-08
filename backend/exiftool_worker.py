"""
MediaVault - ExifTool Worker
Async queue-based ExifTool process manager with atomic writes.
Reads/writes XMP:MediaVault JSON metadata in files.
"""
import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend.config import logger
from backend.sync_engine.watcher import blacklist


# Default MediaVault XMP JSON structure
DEFAULT_METADATA = {
    "version": "1.0",
    "is_favorite": False,
    "tags": [],
}


def _check_exiftool_available() -> bool:
    """Check if exiftool is available in PATH."""
    return shutil.which("exiftool") is not None


def read_xmp_metadata(file_path: Path) -> dict | None:
    """Read XMP:MediaVault JSON metadata from a file using ExifTool."""
    if not _check_exiftool_available():
        logger.warning("ExifTool not found in PATH. Metadata read skipped.")
        return None

    try:
        result = subprocess.run(
            ["exiftool", "-json", "-XMP:MediaVault", str(file_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        if data and len(data) > 0:
            raw = data[0].get("MediaVault", "")
            if raw:
                return json.loads(raw) if isinstance(raw, str) else raw
        return None

    except Exception as e:
        logger.error("ExifTool read failed for %s: %s", file_path, e)
        return None


def write_xmp_metadata(file_path: Path, metadata: dict) -> bool:
    """
    Write XMP:MediaVault JSON metadata to a file using ExifTool.
    Uses atomic write: writes to temp file first, then replaces original.
    Registers file in blacklist to prevent Watchdog infinite loop.
    """
    if not _check_exiftool_available():
        logger.warning("ExifTool not found in PATH. Metadata write skipped.")
        return False

    # Validate metadata against schema
    if "version" not in metadata:
        metadata["version"] = "1.0"
    if "is_favorite" not in metadata:
        metadata["is_favorite"] = False
    if "tags" not in metadata:
        metadata["tags"] = []

    try:
        # Register in blacklist to prevent Watchdog loop
        blacklist.add(file_path)

        # Create temp copy
        temp_dir = file_path.parent
        temp_path = temp_dir / f".mediavault_tmp_{file_path.name}"

        shutil.copy2(str(file_path), str(temp_path))

        # Write metadata to temp file
        json_str = json.dumps(metadata, ensure_ascii=False)
        result = subprocess.run(
            [
                "exiftool",
                "-overwrite_original",
                f"-XMP:MediaVault={json_str}",
                str(temp_path),
            ],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            logger.error("ExifTool write failed: %s", result.stderr)
            temp_path.unlink(missing_ok=True)
            return False

        # Atomic replace: only replace original if temp write succeeded
        shutil.move(str(temp_path), str(file_path))
        logger.debug("XMP metadata written to %s", file_path)
        return True

    except Exception as e:
        logger.error("Atomic write failed for %s: %s", file_path, e)
        # Cleanup temp file on failure
        temp_path = file_path.parent / f".mediavault_tmp_{file_path.name}"
        temp_path.unlink(missing_ok=True)
        return False


class ExifToolQueue:
    """Async queue for sequential ExifTool write operations."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start processing the queue."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("ExifTool queue worker started")

    async def stop(self):
        """Stop the queue worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def enqueue(self, file_path: Path, metadata: dict):
        """Add a write operation to the queue."""
        await self._queue.put((file_path, metadata))

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    async def _process_loop(self):
        """Process queued write operations sequentially."""
        while self._running:
            try:
                file_path, metadata = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                # Run blocking exiftool in executor
                loop = asyncio.get_running_loop()
                success = await loop.run_in_executor(
                    None, write_xmp_metadata, file_path, metadata
                )
                if not success:
                    logger.warning("ExifTool write failed for %s, will not retry", file_path)
                # Schedule blacklist removal 3s later
                loop.call_later(3.0, blacklist.remove, file_path)
                self._queue.task_done()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ExifTool queue error: %s", e)


exiftool_queue = ExifToolQueue()
