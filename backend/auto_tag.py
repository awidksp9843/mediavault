import asyncio
from pathlib import Path

from backend.config import logger
from backend.database import File, Tag, FileTag, Workspace, SessionLocal
from backend.exiftool_worker import exiftool_queue
from backend.websocket_manager import ws_manager


class YOLOModel:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self):
        if self._model is not None:
            return self._model
        logger.info("Loading YOLO model (yolo11n)...")
        from ultralytics import YOLO
        self._model = YOLO("yolo11n.pt")
        logger.info("YOLO model loaded")
        return self._model

    def predict(self, image_path: str):
        model = self.load()
        results = model(image_path, device="cpu", verbose=False)
        return results[0]

    @property
    def class_names(self):
        return self.load().names


yolo_model = YOLOModel()


async def auto_tag_files(file_ids: list[int]):
    db = SessionLocal()

    try:
        files_to_process = (
            db.query(File)
            .filter(
                File.id.in_(file_ids),
                File.is_deleted == False,
                File.media_type == "image",
            )
            .all()
        )
    except Exception as e:
        logger.error("DB query failed: %s", e)
        db.close()
        return

    total = len(files_to_process)
    processed = 0
    errors = 0

    await ws_manager.broadcast_immediate("auto_tag_started", {"total": total})

    if total == 0:
        await ws_manager.broadcast_immediate("auto_tag_completed", {
            "processed": 0, "errors": 0, "total": 0,
        })
        db.close()
        return

    for file_record in files_to_process:
        try:
            workspace = db.query(Workspace).filter(
                Workspace.id == file_record.workspace_id
            ).first()
            if not workspace:
                errors += 1
                continue

            full_path = Path(workspace.absolute_path) / file_record.relative_path
            if not full_path.exists():
                errors += 1
                continue

            result = yolo_model.predict(str(full_path))
            detected = list(set(
                result.boxes.cls.tolist()
            ))
            tags = sorted(
                yolo_model.class_names[int(c)].lower() for c in detected
            )

            if tags:
                db.query(FileTag).filter(
                    FileTag.file_id == file_record.id,
                    FileTag.source == "manual",
                ).delete()

                for tag_name in tags:
                    tag = db.query(Tag).filter(Tag.name == tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.add(tag)
                        db.flush()
                    db.add(FileTag(
                        file_id=file_record.id,
                        tag_id=tag.id,
                        source="manual",
                    ))

                db.commit()

                current_tags = [
                    ft.tag.name
                    for ft in db.query(FileTag)
                    .filter(FileTag.file_id == file_record.id)
                    .all()
                    if ft.tag
                ]
                metadata = {
                    "is_favorite": file_record.is_favorite,
                    "tags": ",".join(current_tags),
                }
                await exiftool_queue.enqueue(full_path, metadata)

            processed += 1

            await ws_manager.broadcast_immediate("auto_tag_progress", {
                "file_id": file_record.id,
                "filename": file_record.filename,
                "tags": tags,
                "current": processed,
                "total": total,
            })

        except Exception as e:
            logger.error("Auto-tag failed for file %d: %s", file_record.id, e)
            errors += 1
            processed += 1

    db.close()

    await ws_manager.broadcast_immediate("auto_tag_completed", {
        "processed": processed,
        "errors": errors,
        "total": total,
    })
