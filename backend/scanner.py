"""
MediaVault - Scanner (Two-Track Phase 1)
Fast indexing: file path/size/extension/hash → DB, then background thumbnail + pHash.
"""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import xxhash
from PIL import Image
from sqlalchemy.orm import Session

from backend.config import (
    ALL_SUPPORTED_EXTENSIONS, get_media_type, logger,
    SUPPORTED_IMAGE_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS,
)
from backend.database import File, Workspace, SessionLocal
from backend.thumbnail_gen.generator import generate_thumbnail
from backend.websocket_manager import ws_manager


def partial_hash(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    xxHash of first 1MB + last 1MB of file for fast dedup detection.
    Falls back to full file hash if file is smaller than 2 * chunk_size.
    """
    hasher = xxhash.xxh64()
    file_size = file_path.stat().st_size

    with open(file_path, "rb") as f:
        # Read first chunk
        hasher.update(f.read(chunk_size))

        if file_size > chunk_size * 2:
            # Seek to last chunk
            f.seek(-chunk_size, os.SEEK_END)
            hasher.update(f.read(chunk_size))
        elif file_size > chunk_size:
            # Read whatever remains
            hasher.update(f.read())

    # Include file size in hash for additional uniqueness
    hasher.update(file_size.to_bytes(8, "little"))
    return hasher.hexdigest()


def get_image_dimensions(file_path: Path) -> tuple[int | None, int | None]:
    """Get image width/height without loading full image into memory."""
    try:
        with Image.open(file_path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def get_video_metadata(file_path: Path) -> dict:
    """Extract video metadata using ffprobe."""
    try:
        import ffmpeg
        probe = ffmpeg.probe(str(file_path))
        video_stream = next(
            (s for s in probe.get("streams", []) if s["codec_type"] == "video"),
            None,
        )
        if not video_stream:
            return {}
        format_info = probe.get("format", {})
        fps_parts = video_stream.get("r_frame_rate", "0/1").split("/")
        fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 and float(fps_parts[1]) > 0 else None
        return {
            "width": int(video_stream.get("width", 0)) or None,
            "height": int(video_stream.get("height", 0)) or None,
            "duration": float(format_info.get("duration", 0)) or None,
            "fps": round(fps, 2) if fps else None,
            "codec": video_stream.get("codec_name"),
            "bitrate": int(format_info.get("bit_rate", 0)) or None,
        }
    except Exception as e:
        logger.warning("Failed to probe video %s: %s", file_path, e)
        return {}


def get_exif_date(file_path: Path) -> datetime | None:
    """Try to extract EXIF creation date from image."""
    try:
        with Image.open(file_path) as img:
            exif_data = img._getexif()
            if exif_data:
                # 36867 = DateTimeOriginal, 36868 = DateTimeDigitized
                for tag_id in (36867, 36868, 306):
                    date_str = exif_data.get(tag_id)
                    if date_str:
                        return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def scan_file(file_path: Path, workspace: Workspace, db: Session) -> File | None:
    """
    Track 1: Index a single file with basic metadata and partial hash.
    Returns the File ORM object or None if unsupported/error.
    """
    ext = file_path.suffix.lower()
    media_type = get_media_type(ext)
    if not media_type:
        return None

    # Build relative path from workspace root
    workspace_path = Path(workspace.absolute_path)
    try:
        relative_path = file_path.relative_to(workspace_path).as_posix()
    except ValueError:
        logger.error("File %s not under workspace %s", file_path, workspace_path)
        return None

    # Check if already indexed (by relative path)
    existing = db.query(File).filter(
        File.workspace_id == workspace.id,
        File.relative_path == relative_path,
        File.is_deleted == False,
    ).first()
    if existing:
        return existing

    try:
        stat = file_path.stat()
        file_hash = partial_hash(file_path)

        file_record = File(
            workspace_id=workspace.id,
            relative_path=relative_path,
            filename=file_path.name,
            extension=ext,
            size=stat.st_size,
            media_type=media_type,
            file_hash=file_hash,
            sync_status="synced",
        )

        # Get dimensions & EXIF date
        if media_type == "image":
            w, h = get_image_dimensions(file_path)
            file_record.width = w
            file_record.height = h
            file_record.media_created_at = get_exif_date(file_path)
        elif media_type == "video":
            vmeta = get_video_metadata(file_path)
            file_record.width = vmeta.get("width")
            file_record.height = vmeta.get("height")
            file_record.duration = vmeta.get("duration")
            file_record.fps = vmeta.get("fps")
            file_record.codec = vmeta.get("codec")
            file_record.bitrate = vmeta.get("bitrate")

        # Fallback created date from filesystem
        if not file_record.media_created_at:
            file_record.media_created_at = datetime.fromtimestamp(
                stat.st_ctime, tz=timezone.utc
            )

        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        return file_record

    except Exception as e:
        logger.error("Failed to scan file %s: %s", file_path, e)
        db.rollback()
        return None


async def scan_workspace(workspace_id: int):
    """
    Scan entire workspace directory and index all media files.
    Track 1: Fast metadata + hash indexing.
    Track 2: Background thumbnail + pHash generation.
    """
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            logger.error("Workspace %d not found", workspace_id)
            return

        workspace_path = Path(workspace.absolute_path)
        if not workspace_path.exists():
            logger.error("Workspace path does not exist: %s", workspace_path)
            return

        logger.info("Starting scan of workspace: %s", workspace_path)
        await ws_manager.broadcast_immediate("scan_started", {"workspace_id": workspace_id})

        total_files = 0
        indexed_files = 0
        thumbnail_tasks = []

        # Walk directory tree
        for root, dirs, files in os.walk(workspace_path):
            # Skip hidden directories and thumbnail/data directories
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("data", "__pycache__", "node_modules")]

            for fname in files:
                file_path = Path(root) / fname
                ext = file_path.suffix.lower()
                if ext not in ALL_SUPPORTED_EXTENSIONS:
                    continue

                total_files += 1
                file_record = scan_file(file_path, workspace, db)
                if file_record:
                    indexed_files += 1
                    # Queue thumbnail generation
                    if not file_record.thumbnail_path:
                        thumbnail_tasks.append((file_record.id, file_path, file_record.media_type))

                # Send progress every 50 files
                if total_files % 50 == 0:
                    await ws_manager.queue_event("scan_progress", {
                        "workspace_id": workspace_id,
                        "total": total_files,
                        "indexed": indexed_files,
                    })

        await ws_manager.broadcast_immediate("scan_progress", {
            "workspace_id": workspace_id,
            "total": total_files,
            "indexed": indexed_files,
            "phase": "metadata_complete",
        })

        logger.info("Track 1 complete: %d/%d files indexed", indexed_files, total_files)

        # Track 2: Generate thumbnails in background
        for file_id, file_path, media_type in thumbnail_tasks:
            try:
                thumb_result = generate_thumbnail(file_path, file_id, media_type)
                if thumb_result:
                    thumb_path, phash_value = thumb_result
                    file_record = db.query(File).filter(File.id == file_id).first()
                    if file_record:
                        file_record.thumbnail_path = thumb_path
                        if phash_value:
                            file_record.phash = phash_value
                        file_record.last_indexed = datetime.now(timezone.utc)
                        db.commit()
            except Exception as e:
                logger.error("Thumbnail generation failed for file %d: %s", file_id, e)

            indexed_files += 1
            if indexed_files % 20 == 0:
                await ws_manager.queue_event("scan_progress", {
                    "workspace_id": workspace_id,
                    "phase": "thumbnails",
                    "processed": indexed_files,
                    "total": len(thumbnail_tasks),
                })

        await ws_manager.broadcast_immediate("scan_complete", {
            "workspace_id": workspace_id,
            "total_files": total_files,
            "indexed_files": indexed_files,
        })
        logger.info("Scan complete for workspace %d", workspace_id)

    except Exception as e:
        logger.error("Workspace scan failed: %s", e)
    finally:
        db.close()
