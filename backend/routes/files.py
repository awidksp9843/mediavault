"""
MediaVault - Files API Routes
Cursor-based pagination, FTS5 search, thumbnail/media serving,
file move, delete operations.
"""
import asyncio
import shutil
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import logger
from backend.database import File, Workspace, Tag, FileTag, get_db, SessionLocal
from backend.exiftool_worker import exiftool_queue
from backend.thumbnail_gen.generator import get_thumbnail_absolute_path, generate_thumbnail
from backend.scanner import scan_workspace
from backend.websocket_manager import ws_manager
from backend.auto_tag import auto_tag_files, yolo_model
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["files"])


# ── Pydantic Models ──

class AutoTagRequest(BaseModel):
    file_ids: list[int]

class AutoTagAllRequest(BaseModel):
    workspace_id: int

class WorkspaceCreate(BaseModel):
    absolute_path: str
    alias: str | None = None

class WorkspaceResponse(BaseModel):
    id: int
    absolute_path: str
    alias: str | None
    file_count: int = 0

class FileResponse_(BaseModel):
    id: int
    workspace_id: int
    relative_path: str
    filename: str
    extension: str
    size: int
    is_favorite: bool
    media_type: str
    width: int | None
    height: int | None
    duration: float | None
    fps: float | None
    codec: str | None
    bitrate: int | None
    file_hash: str | None
    media_created_at: str | None
    thumbnail_path: str | None
    sync_status: str
    phash: str | None
    tags: list[str] = []

class FileMoveRequest(BaseModel):
    file_ids: list[int]
    destination_path: str  # relative path within workspace

class FileListResponse(BaseModel):
    files: list[FileResponse_]
    next_cursor: int | None
    total_count: int


# ── Workspace Endpoints ──

@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db)):
    """Return all registered workspaces with file counts."""
    workspaces = db.query(Workspace).all()
    result = []
    for ws in workspaces:
        count = db.query(func.count(File.id)).filter(
            File.workspace_id == ws.id,
            File.is_deleted == False,
        ).scalar()
        result.append({
            "id": ws.id,
            "absolute_path": ws.absolute_path,
            "alias": ws.alias,
            "file_count": count or 0,
        })
    return result


@router.post("/workspaces")
async def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db)):
    """Register a new workspace and trigger initial scan."""
    ws_path = Path(body.absolute_path).resolve()
    if not ws_path.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not ws_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    existing = db.query(Workspace).filter(Workspace.absolute_path == str(ws_path)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Workspace already registered")

    ws = Workspace(
        absolute_path=str(ws_path),
        alias=body.alias or ws_path.name,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    # Start watching and scanning in background
    loop = asyncio.get_event_loop()
    from backend.sync_engine.watcher import watcher_service
    watcher_service.start_watching(ws.id, ws_path, loop)
    asyncio.create_task(scan_workspace(ws.id))

    return {"id": ws.id, "absolute_path": str(ws_path), "alias": ws.alias}


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: int, db: Session = Depends(get_db)):
    """Unregister a workspace (does NOT delete files)."""
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from backend.sync_engine.watcher import watcher_service
    watcher_service.stop_watching(workspace_id)

    db.delete(ws)
    db.commit()
    return {"message": "Workspace removed"}


@router.post("/workspaces/{workspace_id}/scan")
async def rescan_workspace(workspace_id: int, db: Session = Depends(get_db)):
    """Trigger a rescan of a workspace."""
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    asyncio.create_task(scan_workspace(workspace_id))
    return {"message": "Scan started"}


# ── File List (Cursor-based Pagination) ──

@router.get("/files")
def list_files(
    workspace_id: int,
    cursor: int | None = Query(None, description="Last file ID for cursor pagination"),
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query("media_created_at", regex="^(filename|size|media_created_at|extension)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    media_type: str | None = Query(None, regex="^(image|video)$"),
    folder: str | None = Query(None, description="Filter by folder relative path"),
    is_favorite: bool | None = Query(None, description="Filter by favorite status"),
    db: Session = Depends(get_db),
):
    """List files with cursor-based pagination to avoid large offset DB locks."""
    query = db.query(File).filter(
        File.workspace_id == workspace_id,
        File.is_deleted == False,
    )

    if media_type:
        query = query.filter(File.media_type == media_type)

    if is_favorite is not None:
        query = query.filter(File.is_favorite == is_favorite)

    if folder is not None:
        if folder == "":
            # Root folder: files without "/" in relative_path
            query = query.filter(~File.relative_path.contains("/"))
        else:
            # Specific folder prefix
            query = query.filter(File.relative_path.like(f"{folder}/%"))
            # Exclude files in deeper subfolders
            # Only show direct children of this folder
            query = query.filter(
                ~File.relative_path.like(f"{folder}/%/%")
            )

    # Total count (before cursor filter)
    total = query.count()

    # Sort
    sort_col = getattr(File, sort_by, File.media_created_at)
    if sort_order == "desc":
        query = query.order_by(sort_col.desc(), File.id.desc())
    else:
        query = query.order_by(sort_col.asc(), File.id.asc())

    # Cursor pagination
    if cursor is not None:
        if sort_order == "desc":
            query = query.filter(File.id < cursor)
        else:
            query = query.filter(File.id > cursor)

    files = query.limit(limit + 1).all()

    has_more = len(files) > limit
    if has_more:
        files = files[:limit]

    result_files = []
    for f in files:
        tags = [ft.tag.name for ft in f.file_tags if ft.tag]
        result_files.append({
            "id": f.id,
            "workspace_id": f.workspace_id,
            "relative_path": f.relative_path,
            "filename": f.filename,
            "extension": f.extension,
            "size": f.size,
            "is_favorite": f.is_favorite,
            "media_type": f.media_type,
            "width": f.width,
            "height": f.height,
            "duration": f.duration,
            "fps": f.fps,
            "codec": f.codec,
            "bitrate": f.bitrate,
            "file_hash": f.file_hash,
            "media_created_at": f.media_created_at.isoformat() if f.media_created_at else None,
            "thumbnail_path": f.thumbnail_path,
            "sync_status": f.sync_status,
            "phash": f.phash,
            "tags": tags,
        })

    return {
        "files": result_files,
        "next_cursor": files[-1].id if has_more and files else None,
        "total_count": total,
    }


# ── File Search (FTS5) ──

@router.get("/files/search")
def search_files(
    query: str = Query("", min_length=0),
    workspace_id: int | None = None,
    person: str | None = None,
    tag: str | None = None,
    media_type: str | None = Query(None, regex="^(image|video)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Search files using FTS5 for filenames and tags, plus person filter."""
    from sqlalchemy import text

    base_query = db.query(File).filter(File.is_deleted == False)

    if workspace_id:
        base_query = base_query.filter(File.workspace_id == workspace_id)

    if media_type:
        base_query = base_query.filter(File.media_type == media_type)

    # FTS5 filename search
    if query:
        fts_ids = db.execute(
            text("SELECT rowid FROM files_fts WHERE files_fts MATCH :q"),
            {"q": f"{query}*"},
        ).fetchall()
        fts_file_ids = [row[0] for row in fts_ids]

        # Also search in tags via FTS5
        tag_fts_ids = db.execute(
            text("SELECT rowid FROM tags_fts WHERE tags_fts MATCH :q"),
            {"q": f"{query}*"},
        ).fetchall()
        tag_ids = [row[0] for row in tag_fts_ids]

        if tag_ids:
            tagged_file_ids = [
                ft.file_id for ft in
                db.query(FileTag.file_id).filter(FileTag.tag_id.in_(tag_ids)).all()
            ]
            fts_file_ids = list(set(fts_file_ids + tagged_file_ids))

        # LIKE fallback for partial filename matches (e.g. mid-string search)
        like_ids = [
            row[0] for row in db.execute(
                text("SELECT id FROM files WHERE filename LIKE :q AND is_deleted = 0"),
                {"q": f"%{query}%"},
            ).fetchall()
        ]
        fts_file_ids = list(set(fts_file_ids + like_ids))

        if fts_file_ids:
            base_query = base_query.filter(File.id.in_(fts_file_ids))
        else:
            return {"files": [], "total_count": 0}

    # Tag filter (exact match)
    if tag:
        tag_obj = db.query(Tag).filter(Tag.name == tag).first()
        if tag_obj:
            tagged_ids = [ft.file_id for ft in
                          db.query(FileTag.file_id).filter(FileTag.tag_id == tag_obj.id).all()]
            base_query = base_query.filter(File.id.in_(tagged_ids))
        else:
            return {"files": [], "total_count": 0}

    total = base_query.count()
    files = base_query.order_by(File.media_created_at.desc()).limit(limit).all()

    result_files = []
    for f in files:
        tags_list = [ft.tag.name for ft in f.file_tags if ft.tag]
        result_files.append({
            "id": f.id,
            "workspace_id": f.workspace_id,
            "relative_path": f.relative_path,
            "filename": f.filename,
            "extension": f.extension,
            "size": f.size,
            "is_favorite": f.is_favorite,
            "media_type": f.media_type,
            "width": f.width,
            "height": f.height,
            "duration": f.duration,
            "media_created_at": f.media_created_at.isoformat() if f.media_created_at else None,
            "thumbnail_path": f.thumbnail_path,
            "tags": tags_list,
        })

    return {"files": result_files, "total_count": total}


# ── Thumbnails & Media Serving ──

@router.get("/thumbnails/{file_id}")
def serve_thumbnail(file_id: int, db: Session = Depends(get_db)):
    """Serve WebP thumbnail image. Generates on-the-fly if missing."""
    file_record = db.query(File).filter(File.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if file_record.thumbnail_path:
        thumb_path = get_thumbnail_absolute_path(file_record.thumbnail_path)
        if thumb_path.exists():
            return FileResponse(str(thumb_path), media_type="image/webp")

    workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    full_path = Path(workspace.absolute_path) / file_record.relative_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    thumb_result = generate_thumbnail(full_path, file_record.id, file_record.media_type)
    if not thumb_result:
        raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    thumb_rel, phash_value = thumb_result
    file_record.thumbnail_path = thumb_rel
    if phash_value:
        file_record.phash = phash_value
    db.commit()

    thumb_path = get_thumbnail_absolute_path(thumb_rel)
    return FileResponse(str(thumb_path), media_type="image/webp")


@router.get("/media/{file_id}")
def serve_media(file_id: int, db: Session = Depends(get_db)):
    """Serve original media file with streaming support."""
    file_record = db.query(File).filter(File.id == file_id, File.is_deleted == False).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    full_path = Path(workspace.absolute_path) / file_record.relative_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".heic": "image/heic", ".heif": "image/heif", ".avif": "image/avif",
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
        ".mov": "video/quicktime", ".wmv": "video/x-ms-wmv", ".webm": "video/webm",
        ".m4v": "video/mp4", ".flv": "video/x-flv",
    }
    content_type = media_types.get(file_record.extension, "application/octet-stream")

    return FileResponse(str(full_path), media_type=content_type, filename=file_record.filename)


# ── File Operations ──

@router.post("/files/move")
async def move_files(body: FileMoveRequest, db: Session = Depends(get_db)):
    """Move files to a new location within the workspace."""
    moved = []
    errors = []

    for file_id in body.file_ids:
        file_record = db.query(File).filter(File.id == file_id, File.is_deleted == False).first()
        if not file_record:
            errors.append({"file_id": file_id, "error": "File not found"})
            continue

        workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
        if not workspace:
            errors.append({"file_id": file_id, "error": "Workspace not found"})
            continue

        ws_path = Path(workspace.absolute_path)
        src_path = ws_path / file_record.relative_path
        dest_dir = ws_path / body.destination_path
        dest_path = dest_dir / file_record.filename

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Blacklist to prevent Watchdog loops
            from backend.sync_engine.watcher import blacklist
            blacklist.add(src_path)
            blacklist.add(dest_path)

            shutil.move(str(src_path), str(dest_path))

            new_rel = dest_path.relative_to(ws_path).as_posix()
            file_record.relative_path = new_rel
            db.commit()

            moved.append({"file_id": file_id, "new_path": new_rel})
            await ws_manager.queue_event("file_moved", {
                "file_id": file_id,
                "new_path": new_rel,
            })
        except Exception as e:
            errors.append({"file_id": file_id, "error": str(e)})
            logger.error("File move failed: %s", e)

    return {"moved": moved, "errors": errors}


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, hard: bool = Query(False), db: Session = Depends(get_db)):
    """Delete a file. Default is soft delete; set hard=true for physical deletion."""
    file_record = db.query(File).filter(File.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if hard:
        workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
        if workspace:
            full_path = Path(workspace.absolute_path) / file_record.relative_path
            if full_path.exists():
                from backend.sync_engine.watcher import blacklist
                blacklist.add(full_path)
                full_path.unlink()

        # Delete thumbnail
        if file_record.thumbnail_path:
            thumb_path = get_thumbnail_absolute_path(file_record.thumbnail_path)
            thumb_path.unlink(missing_ok=True)

        db.delete(file_record)
    else:
        file_record.is_deleted = True
        file_record.updated_at = datetime.now(timezone.utc)

    db.commit()
    await ws_manager.queue_event("file_deleted", {"file_id": file_id, "hard": hard})
    return {"message": "File deleted", "hard": hard}


@router.patch("/files/{file_id}/favorite")
async def toggle_favorite(file_id: int, db: Session = Depends(get_db)):
    """Toggle favorite status of a file."""
    file_record = db.query(File).filter(File.id == file_id, File.is_deleted == False).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    file_record.is_favorite = not file_record.is_favorite
    db.commit()

    workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
    if workspace:
        full_path = Path(workspace.absolute_path) / file_record.relative_path
        current_tags = [ft.tag.name for ft in file_record.file_tags if ft.tag]
        metadata = {
            "is_favorite": file_record.is_favorite,
            "tags": ",".join(current_tags),
        }
        await exiftool_queue.enqueue(full_path, metadata)

    return {"file_id": file_id, "is_favorite": file_record.is_favorite}


# ── Auto-tag endpoints ──

@router.post("/files/auto-tag")
async def auto_tag(body: AutoTagRequest):
    """Run YOLO auto-tagging on specific image files."""
    asyncio.create_task(auto_tag_files(body.file_ids))
    return {"message": "Auto-tag started", "file_count": len(body.file_ids)}

@router.post("/files/auto-tag-all")
async def auto_tag_all(body: AutoTagAllRequest, db: Session = Depends(get_db)):
    """Run YOLO auto-tagging on ALL image files in a workspace."""
    image_ids = [
        row[0] for row in db.query(File.id).filter(
            File.workspace_id == body.workspace_id,
            File.is_deleted == False,
            File.media_type == "image",
        ).all()
    ]
    if not image_ids:
        return {"message": "No image files to tag", "file_count": 0}
    asyncio.create_task(auto_tag_files(image_ids))
    return {"message": "Auto-tag started", "file_count": len(image_ids)}


# ── Folder structure endpoint ──

@router.get("/folders")
def list_folders(workspace_id: int, db: Session = Depends(get_db)):
    """Return folder tree structure for a workspace."""
    files = db.query(File.relative_path).filter(
        File.workspace_id == workspace_id,
        File.is_deleted == False,
    ).all()

    folders = set()
    folders.add("")  # root
    for (rel_path,) in files:
        parts = Path(rel_path).parent.as_posix()
        if parts and parts != ".":
            # Add all parent paths
            current = Path(parts)
            while str(current) != ".":
                folders.add(current.as_posix())
                current = current.parent

    # Build tree structure
    folder_list = sorted(folders)
    tree = []
    for f in folder_list:
        depth = 0 if f == "" else f.count("/") + 1
        name = Path(f).name if f else "Root"
        count = db.query(func.count(File.id)).filter(
            File.workspace_id == workspace_id,
            File.is_deleted == False,
            File.relative_path.like(f"{f}/%" if f else "%"),
        ).scalar()
        tree.append({
            "path": f,
            "name": name,
            "depth": depth,
            "file_count": count or 0,
        })

    return tree
