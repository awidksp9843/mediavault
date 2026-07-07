"""
MediaVault - AI API Routes
Status, analyze triggers, download progress.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from backend.database import Workspace, get_db
from backend.ai_workers.manager import ai_manager
from backend.config import logger

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai/status")
def ai_status():
    """Return AI worker status: model load state, queue size, hardware."""
    return ai_manager.get_status()


@router.post("/ai/analyze/{workspace_id}")
async def analyze_workspace(workspace_id: int, background_tasks: BackgroundTasks):
    """Trigger AI analysis on all unprocessed images in a workspace."""
    db = next(get_db())
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
    finally:
        db.close()

    background_tasks.add_task(ai_manager.process_workspace, workspace_id)
    logger.info("AI analysis triggered for workspace %d", workspace_id)
    return {"message": "AI analysis started", "workspace_id": workspace_id}


@router.post("/ai/analyze-file")
async def analyze_file(file_id: int):
    """Analyze a single file with AI (for testing)."""
    from backend.database import File, SessionLocal
    db = SessionLocal()
    try:
        file_record = db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")
        workspace = db.query(Workspace).filter(Workspace.id == file_record.workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        from pathlib import Path
        full_path = Path(workspace.absolute_path) / file_record.relative_path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not on disk")
        await ai_manager.process_single_file(db, file_record, full_path)
        return {"message": "File analyzed", "file_id": file_id}
    finally:
        db.close()
