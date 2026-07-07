"""
MediaVault - Tags API Routes
Bulk tag operations with ExifTool queue integration.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.config import logger
from backend.database import File, Tag, FileTag, Workspace, get_db
from backend.exiftool_worker import exiftool_queue, read_xmp_metadata
from backend.websocket_manager import ws_manager

router = APIRouter(prefix="/api", tags=["tags"])


class TagBulkRequest(BaseModel):
    file_ids: list[int]
    tags: list[str]
    action: str = "add"  # "add" | "remove" | "set"


class TagResponse(BaseModel):
    id: int
    name: str
    file_count: int


@router.post("/files/tags")
async def bulk_tag_files(body: TagBulkRequest, db: Session = Depends(get_db)):
    """Add/remove/set tags on multiple files. Queues ExifTool writes."""
    results = []

    for file_id in body.file_ids:
        file_record = db.query(File).filter(
            File.id == file_id, File.is_deleted == False
        ).first()
        if not file_record:
            results.append({"file_id": file_id, "status": "not_found"})
            continue

        if body.action == "add":
            for tag_name in body.tags:
                tag_name = tag_name.strip().lower()
                if not tag_name:
                    continue
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()

                existing = db.query(FileTag).filter(
                    FileTag.file_id == file_id,
                    FileTag.tag_id == tag.id,
                ).first()
                if not existing:
                    db.add(FileTag(file_id=file_id, tag_id=tag.id, source="manual"))

        elif body.action == "remove":
            for tag_name in body.tags:
                tag_name = tag_name.strip().lower()
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if tag:
                    db.query(FileTag).filter(
                        FileTag.file_id == file_id,
                        FileTag.tag_id == tag.id,
                    ).delete()

        elif body.action == "set":
            # Remove all existing manual tags, then add new ones
            db.query(FileTag).filter(
                FileTag.file_id == file_id,
                FileTag.source == "manual",
            ).delete()
            for tag_name in body.tags:
                tag_name = tag_name.strip().lower()
                if not tag_name:
                    continue
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                db.add(FileTag(file_id=file_id, tag_id=tag.id, source="manual"))

        file_record.sync_status = "pending_write"
        results.append({"file_id": file_id, "status": "queued"})

    db.commit()

    # Queue ExifTool writes for each file
    for file_id in body.file_ids:
        file_record = db.query(File).filter(File.id == file_id).first()
        if not file_record:
            continue

        workspace = db.query(Workspace).filter(
            Workspace.id == file_record.workspace_id
        ).first()
        if not workspace:
            continue

        full_path = Path(workspace.absolute_path) / file_record.relative_path

        # Build metadata JSON
        current_tags = [ft.tag.name for ft in file_record.file_tags if ft.tag]
        metadata = {
            "version": "1.0",
            "is_favorite": file_record.is_favorite,
            "tags": current_tags,
            "persons": [fp.person.name for fp in file_record.file_persons if fp.person and fp.person.name],
        }

        await exiftool_queue.enqueue(full_path, metadata)

    await ws_manager.queue_event("tags_updated", {
        "file_ids": body.file_ids,
        "tags": body.tags,
        "action": body.action,
    })

    return {"results": results}


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)):
    """List all tags with file counts."""
    from sqlalchemy import func
    tags = db.query(
        Tag.id, Tag.name,
        func.count(FileTag.id).label("file_count"),
    ).outerjoin(FileTag).group_by(Tag.id).all()

    return [
        {"id": t.id, "name": t.name, "file_count": t.file_count}
        for t in tags
    ]


@router.get("/files/{file_id}/metadata")
def get_file_metadata(file_id: int, db: Session = Depends(get_db)):
    """Get full metadata for a specific file including XMP data."""
    file_record = db.query(File).filter(File.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    tags = [ft.tag.name for ft in file_record.file_tags if ft.tag]
    persons = []
    for fp in file_record.file_persons:
        if fp.person:
            persons.append({
                "name": fp.person.name,
                "bounding_box": fp.bounding_box,
                "confidence": fp.confidence_score,
            })

    return {
        "id": file_record.id,
        "filename": file_record.filename,
        "relative_path": file_record.relative_path,
        "extension": file_record.extension,
        "size": file_record.size,
        "media_type": file_record.media_type,
        "width": file_record.width,
        "height": file_record.height,
        "duration": file_record.duration,
        "fps": file_record.fps,
        "codec": file_record.codec,
        "bitrate": file_record.bitrate,
        "is_favorite": file_record.is_favorite,
        "file_hash": file_record.file_hash,
        "media_created_at": file_record.media_created_at.isoformat() if file_record.media_created_at else None,
        "sync_status": file_record.sync_status,
        "tags": tags,
        "persons": persons,
    }
