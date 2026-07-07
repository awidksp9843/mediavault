"""
MediaVault - Integrity Checker
Validates consistency between DB records and filesystem on startup.
Handles orphan files (soft delete) and untracked files (new indexing).
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import ALL_SUPPORTED_EXTENSIONS, logger
from backend.database import File, Workspace, SessionLocal
from backend.scanner import scan_file


def check_integrity(workspace_id: int):
    """
    Run integrity check for a workspace:
    1. Mark DB records as deleted if file no longer exists on disk
    2. Index files that exist on disk but are not in DB
    """
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            logger.warning("Integrity check: workspace %d not found", workspace_id)
            return

        workspace_path = Path(workspace.absolute_path)
        if not workspace_path.exists():
            logger.warning("Integrity check: workspace path does not exist: %s", workspace_path)
            return

        logger.info("Running integrity check for workspace %d (%s)", workspace_id, workspace_path)

        # Step 1: Check for orphan DB records (file no longer on disk)
        orphan_count = 0
        active_files = db.query(File).filter(
            File.workspace_id == workspace_id,
            File.is_deleted == False,
        ).all()

        for file_record in active_files:
            full_path = workspace_path / file_record.relative_path
            if not full_path.exists():
                file_record.is_deleted = True
                file_record.updated_at = datetime.now(timezone.utc)
                orphan_count += 1

        if orphan_count > 0:
            db.commit()
            logger.info("Integrity check: soft-deleted %d orphan records", orphan_count)

        # Step 2: Find untracked files on disk
        tracked_paths = set()
        all_db_files = db.query(File.relative_path).filter(
            File.workspace_id == workspace_id,
            File.is_deleted == False,
        ).all()
        for (rp,) in all_db_files:
            tracked_paths.add(rp)

        untracked_count = 0
        for root_dir, dirs, files in workspace_path.walk():
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("data", "__pycache__", "node_modules")]
            for fname in files:
                file_path = root_dir / fname
                ext = file_path.suffix.lower()
                if ext not in ALL_SUPPORTED_EXTENSIONS:
                    continue
                try:
                    rel_path = file_path.relative_to(workspace_path).as_posix()
                except ValueError:
                    continue
                if rel_path not in tracked_paths:
                    scan_file(file_path, workspace, db)
                    untracked_count += 1

        logger.info(
            "Integrity check complete: %d orphans removed, %d untracked files indexed",
            orphan_count, untracked_count,
        )

    except Exception as e:
        logger.error("Integrity check failed: %s", e)
        db.rollback()
    finally:
        db.close()


def check_all_workspaces():
    """Run integrity check for all registered workspaces."""
    db = SessionLocal()
    try:
        workspaces = db.query(Workspace).all()
        for ws in workspaces:
            check_integrity(ws.id)
    finally:
        db.close()
