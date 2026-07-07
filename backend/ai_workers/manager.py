"""
MediaVault - AI Pipeline Manager
Orchestrates model lazy loading, per-file inference, DB updates,
and WebSocket progress delivery.
"""
import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.config import AI_MODEL_CACHE_DIR, logger
from backend.database import File, Tag, FileTag, Person, FilePerson, Workspace, SessionLocal
from backend.websocket_manager import ws_manager
from backend.ai_workers.models import BLIPCaptioner, Places365Classifier, InsightFaceDetector


class AIWorkerManager:
    def __init__(self):
        self._models_status = {
            "blip": {"status": "not_loaded", "device": "cpu"},
            "places365": {"status": "not_loaded", "device": "cpu"},
            "insightface": {"status": "not_loaded", "device": "cpu"},
        }
        self.blip = BLIPCaptioner()
        self.places365 = Places365Classifier()
        self.insightface = InsightFaceDetector()
        self._queue_size = 0
        self._batch_size = 1

    # ── Status ──

    def _update_status(self, name: str, status: str):
        self._models_status[name]["status"] = status

    def get_status(self) -> dict:
        return {
            "models": self._models_status,
            "hardware": {"device": "cpu", "platform": __import__("platform").system()},
            "batch_size": self._batch_size,
            "queue_remaining": self._queue_size,
            "cache_dir": str(AI_MODEL_CACHE_DIR),
        }

    # ── Model Download ──

    async def download_models(self):
        """Download all model weights with progress broadcast."""
        await ws_manager.broadcast_immediate("ai_download_progress", {
            "model": "BLIP captioner",
            "progress": 0,
            "status": "downloading",
        })
        self._update_status("blip", "downloading")
        try:
            self.blip.load()
            self._update_status("blip", "loaded")
            self.blip.unload()
        except Exception as e:
            logger.error("BLIP download failed: %s", e)
            self._update_status("blip", "error")

        await ws_manager.broadcast_immediate("ai_download_progress", {
            "model": "Places365 scene classifier",
            "progress": 33,
            "status": "downloading",
        })
        self._update_status("places365", "downloading")
        try:
            self.places365.load()
            self._update_status("places365", "loaded")
            self.places365.unload()
        except Exception as e:
            logger.error("Places365 download failed: %s", e)
            self._update_status("places365", "error")

        await ws_manager.broadcast_immediate("ai_download_progress", {
            "model": "InsightFace face detector",
            "progress": 66,
            "status": "downloading",
        })
        self._update_status("insightface", "downloading")
        try:
            self.insightface.load()
            self._update_status("insightface", "loaded")
            self.insightface.unload()
        except Exception as e:
            logger.error("InsightFace download failed: %s", e)
            self._update_status("insightface", "error")

        await ws_manager.broadcast_immediate("ai_download_progress", {
            "model": "",
            "progress": 100,
            "status": "complete",
        })

    # ── Workspace Analysis ──

    async def process_workspace(self, workspace_id: int):
        """Analyze all unprocessed image files in a workspace."""
        self._queue_size = 0
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if not workspace:
                logger.error("Workspace %d not found", workspace_id)
                return

            ws_path = Path(workspace.absolute_path)
            files_to_process = db.query(File).filter(
                File.workspace_id == workspace_id,
                File.media_type == "image",
                File.is_deleted == False,
                File.last_indexed.is_(None),
            ).all()

            if not files_to_process:
                files_to_process = db.query(File).filter(
                    File.workspace_id == workspace_id,
                    File.media_type == "image",
                    File.is_deleted == False,
                ).limit(5).all()

            total = len(files_to_process)
            if total == 0:
                await ws_manager.broadcast_immediate("ai_progress", {
                    "current": 0, "total": 0, "filename": "", "phase": "no_files",
                })
                return

            self._queue_size = total
            await ws_manager.broadcast_immediate("ai_progress", {
                "current": 0, "total": total, "filename": "", "phase": "starting",
            })

            for idx, file_record in enumerate(files_to_process, 1):
                full_path = ws_path / file_record.relative_path
                if not full_path.exists():
                    continue

                await ws_manager.queue_event("ai_progress", {
                    "current": idx,
                    "total": total,
                    "filename": file_record.filename,
                    "phase": "analyzing",
                })

                try:
                    await self.process_single_file(db, file_record, full_path)
                except Exception as e:
                    logger.error("AI analysis failed for file %d: %s", file_record.id, e)
                    file_record.retry_count = (file_record.retry_count or 0) + 1
                    db.commit()

                self._queue_size = total - idx

            await ws_manager.broadcast_immediate("ai_progress", {
                "current": total, "total": total, "filename": "", "phase": "complete",
            })

            # Unload models to free memory
            self.blip.unload()
            self.places365.unload()
            self.insightface.unload()
            for name in self._models_status:
                self._update_status(name, "not_loaded")

        except Exception as e:
            logger.error("Workspace AI analysis failed: %s", e)
        finally:
            db.close()

    async def process_single_file(self, db: Session, file_record: File, full_path: Path):
        """Run all AI models on one file and store results."""
        blip_tags, places_tags, face_results = await asyncio.gather(
            self._run_blip(full_path),
            self._run_places365(full_path),
            self._run_insightface(full_path, db, file_record),
        )

        # Store BLIP tags
        all_tags = list(set(blip_tags + [t["label"] for t in places_tags]))
        for tag_name in all_tags:
            if not tag_name:
                continue
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
                db.flush()
            existing = db.query(FileTag).filter(
                FileTag.file_id == file_record.id,
                FileTag.tag_id == tag.id,
            ).first()
            if not existing:
                db.add(FileTag(file_id=file_record.id, tag_id=tag.id, source="ai", confidence_score=0.8))

        # Store Persons (from insightface)
        for face in face_results:
            if face.get("embedding") is None:
                continue
            person = None
            # Simple clustering: check if similar embedding exists
            existing_persons = db.query(Person).all()
            for ep in existing_persons:
                if ep.representative_encoding:
                    import json
                    enc = json.loads(ep.representative_encoding)
                    sim = self._cosine_similarity(face["embedding"], enc)
                    if sim > 0.5:
                        person = ep
                        break
            if not person:
                person = Person(
                    representative_encoding=json.dumps(face["embedding"]),
                )
                db.add(person)
                db.flush()

            existing_fp = db.query(FilePerson).filter(
                FilePerson.file_id == file_record.id,
                FilePerson.person_id == person.id,
            ).first()
            if not existing_fp:
                db.add(FilePerson(
                    file_id=file_record.id,
                    person_id=person.id,
                    bounding_box=json.dumps(face["bbox"]),
                    confidence_score=face["confidence"],
                ))

        file_record.last_indexed = datetime.now(timezone.utc)
        db.commit()

    async def _run_blip(self, path: Path) -> list[str]:
        loop = asyncio.get_event_loop()
        self._update_status("blip", "loaded")
        self.blip.load()
        return await loop.run_in_executor(None, self.blip.predict, str(path))

    async def _run_places365(self, path: Path) -> list[dict]:
        loop = asyncio.get_event_loop()
        self._update_status("places365", "loaded")
        self.places365.load()
        return await loop.run_in_executor(None, self.places365.predict, str(path))

    async def _run_insightface(self, path: Path, db: Session, file_record: File) -> list[dict]:
        loop = asyncio.get_event_loop()
        self._update_status("insightface", "loaded")
        self.insightface.load()
        return await loop.run_in_executor(None, self.insightface.predict, str(path))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        import numpy as np
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


ai_manager = AIWorkerManager()
